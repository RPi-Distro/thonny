#!/bin/bash

LOCAL_FRAMEWORKS=$HOME/thonny_template_build/Thonny.app/Contents/Frameworks

rm -rf $LOCAL_FRAMEWORKS/SDL*

mkdir -p $LOCAL_FRAMEWORKS

cp -R /Library/Frameworks/SDL.framework $LOCAL_FRAMEWORKS
cp -R /Library/Frameworks/SDL_image.framework $LOCAL_FRAMEWORKS
cp -R /Library/Frameworks/SDL_mixer.framework $LOCAL_FRAMEWORKS
cp -R /Library/Frameworks/SDL_ttf.framework $LOCAL_FRAMEWORKS
