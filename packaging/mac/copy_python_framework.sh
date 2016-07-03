#!/bin/bash
# https://github.com/lektor/lektor/blob/master/gui/bin/make-python-framework-relocatable

# Take from env
# LOCAL_FRAMEWORKS=$HOME/thonny_template_build/Thonny.app/Contents/Frameworks

VERSION=3.5
ORIGINAL_FRAMEWORK_PATH=/Library/Frameworks/Python.framework
NEW_FRAMEWORK_PATH=$LOCAL_FRAMEWORKS/Python.framework

rm -rf $NEW_FRAMEWORK_PATH
mkdir -p $NEW_FRAMEWORK_PATH

cp -R $ORIGINAL_FRAMEWORK_PATH/* $NEW_FRAMEWORK_PATH

BIN_EXE=$NEW_FRAMEWORK_PATH/Versions/$VERSION/bin/python$VERSION

# delete everything in bin except python3.5
#find $NEW_FRAMEWORK_PATH/Versions/$VERSION/bin -type f -maxdepth 1 ! -name python$VERSION -delete

# Make main binaries and libraries relocatable
BUNDLE_EXE=$NEW_FRAMEWORK_PATH/Versions/$VERSION/Resources/Python.app/Contents/MacOS/Python
ORIG_MAIN_LIB=$ORIGINAL_FRAMEWORK_PATH/Versions/$VERSION/Python
NEW_MAIN_LIB=$NEW_FRAMEWORK_PATH/Versions/$VERSION/Python
MAIN_LIB_LOCAL_NAME=@rpath/Python.framework/Versions/$VERSION/Python

chmod u+w $NEW_MAIN_LIB $BIN_EXE $BUNDLE_EXE

install_name_tool -change $ORIG_MAIN_LIB $MAIN_LIB_LOCAL_NAME $BIN_EXE 
install_name_tool -add_rpath @executable_path/../../../../ $BIN_EXE

install_name_tool -id @rpath/Python.framework/Versions/$VERSION/Python $NEW_MAIN_LIB


install_name_tool -change $ORIG_MAIN_LIB $MAIN_LIB_LOCAL_NAME $BUNDLE_EXE
install_name_tool -add_rpath @executable_path/../../../../../../../ $BUNDLE_EXE

# TODO: update curses libraries links in lib

