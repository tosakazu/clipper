#!/bin/bash

# エラーが発生した場合にスクリプトを終了
set -e

echo "=== Stream Recording Tool Setup ==="
echo "Starting setup process..."

# Python環境の確認とvenv作成
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo "Python3 is not installed. Please install Python 3.8 or later."
        exit 1
    fi
    
    echo "Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
}

# 必要なPythonパッケージのインストール
install_python_packages() {
    echo "Installing required Python packages..."
    pip install --upgrade pip
    pip install fastapi uvicorn pydantic python-multipart aiofiles
}

# システム依存パッケージのインストール
install_system_packages() {
    if [ "$(uname)" == "Darwin" ]; then
        # macOS
        echo "Installing system packages using Homebrew..."
        if ! command -v brew &> /dev/null; then
            echo "Homebrew is not installed. Please install Homebrew first."
            exit 1
        fi
        brew install ffmpeg streamlink
        
    elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
        # Ubuntu/Debian系
        if command -v apt-get &> /dev/null; then
            echo "Installing system packages using apt..."
            sudo apt-get update
            sudo apt-get install -y ffmpeg python3-pip
            sudo pip3 install streamlink
            
        # RHEL/CentOS系
        elif command -v yum &> /dev/null; then
            echo "Installing system packages using yum..."
            sudo yum install -y epel-release
            sudo yum install -y ffmpeg python3-pip
            sudo pip3 install streamlink
        else
            echo "Unsupported Linux distribution. Please install ffmpeg and streamlink manually."
            exit 1
        fi
    else
        echo "Unsupported operating system. Please install ffmpeg and streamlink manually."
        exit 1
    fi
}

# ディレクトリ構造の作成
create_directories() {
    echo "Creating required directories..."
    mkdir -p static recordings clips/trimmed
}

# セットアップの実行
main() {
    mkdir clips
    mkdir recordings
    check_python
    install_python_packages
    install_system_packages
    create_directories
    
    echo ""
    echo "=== Setup Complete ==="
    echo "To start using the tool:"
    echo "1. Activate the virtual environment: source venv/bin/activate"
    echo "2. Run the server: python main.py"
    echo "3. Access the web interface at: http://localhost:8866"
}

# メイン処理の実行
main