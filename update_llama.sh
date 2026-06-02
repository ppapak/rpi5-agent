#!/bin/bash
set -e

BASE_DIR=${BASE_DIR:-$(pwd)}

echo Checking Inference Engine...

if [ ! -d $BASE_DIR/llama.cpp ]; then
    echo Cloning and building llama.cpp...
    cd $BASE_DIR
    git clone https://github.com/ggerganov/llama.cpp
    cd llama.cpp
    mkdir build
    cd build
    cmake ..
    cmake --build . --config Release -j 4
elif [ ! -f $BASE_DIR/llama.cpp/build/bin/llama-server ]; then
    echo Directory exists but binary is missing. Rebuilding...
    cd $BASE_DIR/llama.cpp
    rm -rf build
    mkdir build
    cd build
    cmake ..
    cmake --build . --config Release -j 4
else
    echo Repository and binary exist. Checking for upstream updates...
    cd $BASE_DIR/llama.cpp
    git fetch origin master
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/master)
    if [ $LOCAL != $REMOTE ]; then
        echo New updates detected. Updating source code and rebuilding...
        git pull origin master
        rm -rf build
        mkdir build
        cd build
        cmake ..
        cmake --build . --config Release -j 4
    else
        echo Llama server binary exists and is up to date.
    fi
fi