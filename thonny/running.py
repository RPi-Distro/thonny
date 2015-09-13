# -*- coding: utf-8 -*-

"""Code for maintaining the background process and for running
user programs

Commands get executed via shell, this way the command line in the 
shell becomes kind of title for the execution.

""" 


from _thread import start_new_thread
import collections
from logging import info, debug
import os.path
import subprocess
import sys
import threading

from thonny.common import serialize_message, ToplevelCommand, \
    quote_path_for_shell, \
    InlineCommand, parse_shell_command, unquote_path, \
    CommandSyntaxError, parse_message, DebuggerCommand, InputSubmission
from thonny.globals import get_workbench, get_runner
from thonny.shell import ShellView


COMMUNICATION_ENCODING = "UTF-8"

class Runner:
    def __init__(self):
        get_workbench().add_option("run.working_directory", os.path.expanduser("~"))
        get_workbench().add_option("run.auto_cd", True)
        
        self._proxy = _BackendProxy(get_workbench().get_option("run.working_directory"),
            get_workbench().get_installation_dir())
        
        get_workbench().add_view(ShellView, "Shell", "s",
            visible_by_default=True,
            default_position_key='A')
        
        self._init_commands()
        
        self._poll_vm_messages()
        self._advance_background_tk_mainloop()
    
    def _init_commands(self):
        shell = get_workbench().get_view("ShellView")
        shell.add_command("Run", self.handle_execute_from_shell)
        shell.add_command("Reset", self._handle_reset_from_shell)
        shell.add_command("cd", self._handle_cd_from_shell)
        
        get_workbench().add_command('run_current_script', "run", 'Run current script',
            handler=self._cmd_run_current_script,
            default_sequence="<F5>",
            tester=self.cmd_execution_command_enabled,
            group=10)
        
        get_workbench().add_command('reset', "run", 'Stop/Reset',
            handler=self._cmd_reset,
            default_sequence=None, # TODO:
            group=70)
        
    def get_cwd(self):
        return self._proxy.cwd
    
    def get_state(self):
        """State is one of "running", "waiting_input", "waiting_debug_command",
            "waiting_toplevel_command"
        """
        return self._proxy.get_state()
    
    def send_command(self, cmd):
        self._proxy.send_command(cmd)
    
    def send_program_input(self, data):
        self._proxy.send_program_input(data)
        
    def execute_current(self, mode):
        """
        This method's job is to create a command for running/debugging
        current file/script and submit it to shell
        """
        
        editor = get_workbench().get_current_editor()
        if not editor:
            return

        filename = editor.get_filename(True)
        if not filename:
            return
        
        # changing dir may be required
        script_dir = os.path.dirname(filename)
        
        if (get_workbench().get_option("run.auto_cd") and mode[0].isupper()
            and self._proxy.cwd != script_dir):
            # create compound command
            # start with %cd
            cmd_line = "%cd " + quote_path_for_shell(script_dir) + "\n"
            next_cwd = script_dir
        else:
            # create simple command
            cmd_line = ""
            next_cwd = self._proxy.cwd
        
        # append main command (Run, run, Debug or debug)
        rel_filename = os.path.relpath(filename, next_cwd)
        cmd_line += "%" + mode + " " + quote_path_for_shell(rel_filename) + "\n"
        
        # submit to shell (shell will execute it)
        get_workbench().get_view("ShellView").submit_command(cmd_line)
        
    def handle_execute_from_shell(self, cmd_line):
        """
        Handles all commands that take a filename and 0 or more extra arguments.
        Passes the command to backend.
        
        (Debugger plugin may also use this method)
        """
        command, args = parse_shell_command(cmd_line)
        
        if len(args) >= 1:
            get_workbench().get_editor_notebook().save_all_named_editors()
            self.send_command(ToplevelCommand(command=command,
                               filename=unquote_path(args[0]),
                               args=args[1:]))
        else:
            raise CommandSyntaxError("Command '%s' takes at least one argument", command)

    def _handle_reset_from_shell(self, cmd_line):
        command, args = parse_shell_command(cmd_line)
        assert command == "Reset"
        
        if len(args) == 0:
            self.send_command(ToplevelCommand(command="Reset"))
        else:
            raise CommandSyntaxError("Command 'Reset' doesn't take arguments")
        

    def _handle_cd_from_shell(self, cmd_line):
        command, args = parse_shell_command(cmd_line)
        assert command == "cd"
        
        if len(args) == 1:
            self.send_command(ToplevelCommand(command="cd", path=unquote_path(args[0])))
        else:
            raise CommandSyntaxError("Command 'cd' takes one argument")

    def cmd_execution_command_enabled(self):
        return (self._proxy.get_state() == "waiting_toplevel_command"
                and get_workbench().get_editor_notebook().get_current_editor() is not None)
    
    def _cmd_run_current_script(self):
        self.execute_current("Run")
    
    
    def _cmd_reset(self):
        if get_runner().get_state() == "waiting_toplevel_command":
            get_workbench().get_view("ShellView").submit_command("%Reset\n")
        else:
            get_runner().send_command(ToplevelCommand(command="Reset"))
    

            
    def _advance_background_tk_mainloop(self):
        """Enables running Tkinter programs which doesn't call mainloop. 
        
        When mainloop is omitted, then program can be interacted with
        from the shell after it runs to the end.
        """
        if self._proxy.get_state() == "waiting_toplevel_command":
            self._proxy.send_command(InlineCommand("tkupdate"))
        get_workbench().after(50, self._advance_background_tk_mainloop)
        
    def _poll_vm_messages(self):
        """I chose polling instead of event_generate
        because event_generate across threads is not reliable
        http://www.thecodingforums.com/threads/more-on-tk-event_generate-and-threads.359615/
        """
        while True:
            msg = self._proxy.fetch_next_message()
            if not msg:
                break
            
            debug("Runner: Fetched msg: %s", msg)
            get_workbench().event_generate(msg["message_type"], **msg)
            
            # TODO: maybe distinguish between workbench cwd and backend cwd ??
            get_workbench().set_option("run.working_directory", self._proxy.cwd, save_now=False)
            get_workbench().update_idletasks()
            
        get_workbench().after(50, self._poll_vm_messages)
    

class _BackendProxy:
    def __init__(self, default_cwd, main_dir):
        if os.path.exists(default_cwd):
            self.cwd = default_cwd
        else:
            self.cwd = os.path.expanduser("~")
            
        self.thonny_dir = main_dir
        self._proc = None
        self._state = None
        self._message_queue = None
        self._state_lock = threading.RLock()
        
    def fetch_next_message(self):
        if not self._message_queue or len(self._message_queue) == 0:
            return None
        
        msg = self._message_queue.popleft()
        
        if msg["message_type"] == "Output":
            # combine available output messages to one single message, 
            # in order to put less pressure on UI code
            
            while True:
                if len(self._message_queue) == 0:
                    return msg
                else:
                    next_msg = self._message_queue.popleft()
                    if (next_msg["message_type"] == "Output" 
                        and next_msg["stream_name"] == msg["stream_name"]):
                        msg["data"] += next_msg["data"]
                    else:
                        # not same type of message, put it back
                        self._message_queue.appendleft(next_msg)
                        return msg
            
        else: 
            return msg
    
    def send_command(self, cmd):
        if not (isinstance(cmd, InlineCommand) and cmd.command == "tkupdate"): 
            info("Proxy: Sending command: %s", cmd)
            
        with self._state_lock:
            if (isinstance(cmd, ToplevelCommand) 
                or isinstance(cmd, DebuggerCommand)
                or isinstance(cmd, InputSubmission)):
                self._set_state("running")
            
            if isinstance(cmd, ToplevelCommand) and cmd.command in ("Run", "Debug", "Reset"):
                self._kill_current_process()
                self._start_new_process(cmd)
                 
            self._proc.stdin.write((serialize_message(cmd) + "\n").encode(COMMUNICATION_ENCODING))
            self._proc.stdin.flush() 
            
            if not (hasattr(cmd, "command") and cmd.command == "tkupdate"):
                debug("BackendProxy: sent a command in state %s: %s", self._state, cmd)
    
    def send_program_input(self, data):
        self.send_command(InputSubmission(data=data))
        
    def get_state(self):
        with self._state_lock:
            return self._state
    
    def _set_state(self, state):
        if self._state != state:
            debug("BackendProxy state %s ==> %s", self._state, state)
            self._state = state
    
    
    def _kill_current_process(self):
        if self._proc is not None and self._proc.poll() is None: 
            self._proc.kill()
            self._proc = None
            self._message_queue = None
        
    def _start_new_process(self, cmd):
        self._message_queue = collections.deque()
    
        # create new backend process
        my_env = os.environ.copy()
        my_env["PYTHONIOENCODING"] = COMMUNICATION_ENCODING
        my_env["PYTHONUNBUFFERED"] = "1"
        
        # TODO: backend should be selectable by the user
        if "thonny" in os.path.basename(sys.executable).lower():
            # Thonny is run frozen, therefore also run frozen backend
            cmd_line = [os.path.join(
                            os.path.dirname(sys.executable),
                            os.path.basename(sys.executable)
                                .replace("frontend", "backend"))]
        else:
            cmd_line = [sys.executable, 
                        '-u', # -u means unbuffered IO (neccessary in Python 3.1)
                        os.path.join(self.thonny_dir, "thonny_backend.py")]

        if hasattr(cmd, "filename"):
            cmd_line.append(cmd.filename)
            if hasattr(cmd, "args"):
                cmd_line.extend(cmd.args)
            
        
        info("Starting the backend: %s %s", cmd_line, self.cwd)
        self._proc = subprocess.Popen (
            cmd_line,
            #bufsize=0,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=my_env
        )
        
        # setup asynchronous output listeners
        start_new_thread(self._listen_stdout, ())
        start_new_thread(self._listen_stderr, ())
    
    def _listen_stdout(self):
        #debug("... started listening to stdout")
        # will be called from separate thread
        while True:
            data = self._proc.stdout.readline().decode(COMMUNICATION_ENCODING)
            #debug("... read some stdout data", repr(data))
            if data == '':
                break
            else:
                msg = parse_message(data)
                if "cwd" in msg:
                    self.cwd = msg["cwd"]
                    
                with self._state_lock:
                    self._message_queue.append(msg)
                    if msg["message_type"] == "ToplevelResult":
                        self._set_state("waiting_toplevel_command") 
                    elif msg["message_type"] == "DebuggerProgress":
                        self._set_state("waiting_debug_command") 
                    elif msg["message_type"] == "InputRequest":
                        self._set_state("waiting_input") 

    def _listen_stderr(self):
        # stderr is used only for debugger debugging
        while True:
            data = self._proc.stderr.readline().decode(COMMUNICATION_ENCODING)
            if data == '':
                break
            else:
                debug("### BACKEND ###: %s", data.strip())
        
            