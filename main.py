from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn
from pathlib import Path
from services.recorder import StreamRecorder
from services.clipper import StreamClipper
from datetime import datetime
from typing import Dict
import logging

class StreamManager:
    def __init__(self):
        self.active_streams = {}  # {window_id: {'url': str, 'is_recording': bool}}

    def add_stream(self, window_id: str, url: str, is_recording: bool = False):
        self.active_streams[window_id] = {
            'url': url,
            'is_recording': is_recording
        }

    def remove_stream(self, window_id: str):
        if window_id in self.active_streams:
            del self.active_streams[window_id]

    def get_stream_info(self, window_id: str):
        return self.active_streams.get(window_id)

    def get_all_streams(self):
        return self.active_streams

    def update_recording_status(self, window_id: str, is_recording: bool):
        if window_id in self.active_streams:
            self.active_streams[window_id]['is_recording'] = is_recording

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORSミドルウェアの追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバルな状態管理
recorders: Dict[str, StreamRecorder] = {}
stream_manager = StreamManager()

# 必要なディレクトリのパス設定
STATIC_DIR = Path(__file__).parent / "static"
RECORDINGS_DIR = Path(__file__).parent / "recordings"
CLIPS_DIR = Path(__file__).parent / "clips"
TRIMMED_DIR = CLIPS_DIR / "trimmed"

# ディレクトリの作成
for dir_path in [STATIC_DIR, RECORDINGS_DIR, CLIPS_DIR, TRIMMED_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Directory created/confirmed: {dir_path}")

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# リクエストモデルの定義
class StreamInfo(BaseModel):
    url: str
    window_id: int
    buffer_minutes: int
    quality: str

class ClipRequest(BaseModel):
    url: str
    window_id: int
    duration: int

class ClipTrimRequest(BaseModel):
    clip_path: str
    start_time: float
    end_time: float
    output_name: str
    quality: str

@app.get("/")
async def root():
    """メインページの配信"""
    try:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            logger.error(f"index.html not found at {index_path}")
            return HTMLResponse(content="<h1>Error: index.html not found</h1>", status_code=404)
        
        logger.info(f"Serving index.html from {index_path}")
        return FileResponse(index_path)
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 変更点: clip-editor.html をサーバー経由で取得するためのルート
@app.get("/clip-editor", response_class=HTMLResponse)
async def serve_clip_editor(request: Request):
    """
    clip-editor.html を返す。
    ?clipPath=xxxx というクエリパラメータが付与される想定。
    """
    clip_editor_path = STATIC_DIR / "clip-editor.html"
    if not clip_editor_path.exists():
        return HTMLResponse("<h1>Error: clip-editor.html not found</h1>", status_code=404)
    return FileResponse(clip_editor_path)

@app.get("/api/test")
async def test_endpoint():
    """APIが機能しているかテストするエンドポイント"""
    return {"status": "ok", "message": "API is working"}

@app.get("/api/streams")
async def get_streams():
    """現在のストリーム状態を取得"""
    all_streams = stream_manager.get_all_streams()
    return {"streams": all_streams}

@app.get("/api/recording-status/{window_id}")
async def get_recording_status(window_id: str):
    """録画状態を取得するエンドポイント"""
    try:
        if window_id in recorders:
            status = recorders[window_id].get_status()
            logger.info(f"Status for window {window_id}: {status}")
            return status
        return {"is_recording": False}
    except Exception as e:
        logger.error(f"Error getting recording status: {e}")
        return {"is_recording": False, "error": str(e)}

@app.post("/api/start-recording")
async def start_recording(stream_info: StreamInfo):
    """録画を開始するエンドポイント"""
    window_id = str(stream_info.window_id)
    logger.info(f"Starting recording for window {window_id} with URL {stream_info.url}")
    
    try:
        # 既存の録画を停止
        if window_id in recorders:
            logger.info(f"Stopping existing recording for window {window_id}")
            recorders[window_id].stop()
        
        base_dir = RECORDINGS_DIR / f"window_{window_id}"
        recorder = StreamRecorder(
            url=stream_info.url,
            base_dir=str(base_dir),
            buffer_minutes=stream_info.buffer_minutes,
            quality=stream_info.quality
        )
        success = recorder.start()
        
        if success:
            recorders[window_id] = recorder
            stream_manager.add_stream(window_id, stream_info.url, True)
            logger.info(f"Recording started successfully for window {window_id}")
            return {"status": "started", "success": True}
        else:
            logger.error(f"Failed to start recording for window {window_id}")
            return {"status": "failed", "success": False}
            
    except Exception as e:
        logger.error(f"Error in start_recording: {e}")
        return {"status": "error", "success": False, "message": str(e)}

@app.post("/api/stop-recording")
async def stop_recording(stream_info: StreamInfo):
    """録画を停止するエンドポイント"""
    window_id = str(stream_info.window_id)
    logger.info(f"Stopping recording for window {window_id}")
    
    try:
        if window_id in recorders:
            recorders[window_id].stop()
            del recorders[window_id]
            stream_manager.update_recording_status(window_id, False)
            return {"status": "stopped"}
        return {"status": "not_recording"}
    except Exception as e:
        logger.error(f"Error stopping recording: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/create-clip")
async def create_clip(clip_request: ClipRequest):
    """クリップを作成するエンドポイント"""
    window_id = str(clip_request.window_id)
    logger.info(f"Creating clip for window {window_id}")
    
    try:
        if window_id not in recorders:
            logger.error(f"No active recorder for window {window_id}")
            raise HTTPException(status_code=400, detail="Not recording")
        
        recorder_dir = RECORDINGS_DIR / f"window_{window_id}"
        if not recorder_dir.exists():
            logger.error(f"Recording directory not found: {recorder_dir}")
            raise HTTPException(status_code=404, detail="Recording directory not found")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = CLIPS_DIR / f"clip_{window_id}_{timestamp}.mp4"
        
        logger.info(f"Creating clipper with base dir: {recorder_dir}")
        clipper = StreamClipper(str(recorder_dir))
        
        logger.info(f"Attempting to create clip with duration {clip_request.duration} minutes")
        success = clipper.create_clip(
            duration=clip_request.duration,
            output_path=str(output_path)
        )
        
        if success:
            logger.info(f"Clip created successfully: {output_path}")
            return {"status": "success", "clip_path": output_path.name}
        else:
            logger.error("Failed to create clip - clipper returned False")
            raise HTTPException(status_code=500, detail="Failed to create clip")
            
    except Exception as e:
        logger.error(f"Error in create_clip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/clips/{filename}")
async def get_clip(filename: str):
    """クリップファイルを取得するエンドポイント"""
    try:
        file_path = CLIPS_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Clip not found")
        return FileResponse(file_path)
    except Exception as e:
        logger.error(f"Error serving clip file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 必要なディレクトリの設定
CLIPS_DIR = Path(__file__).parent / "clips"
TRIMMED_DIR = CLIPS_DIR / "trimmed"

@app.get("/trimmed/{filename}")
async def get_trimmed_file(filename: str):
    """トリミング済みクリップを提供するエンドポイント"""
    file_path = TRIMMED_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Trimmed clip not found")
    return FileResponse(file_path)

@app.post("/api/trim-clip")
async def trim_clip(trim_request: ClipTrimRequest):
    """クリップをトリムするエンドポイント"""
    try:
        input_path = CLIPS_DIR / trim_request.clip_path
        output_path = TRIMMED_DIR / trim_request.output_name
        
        if not input_path.exists():
            raise HTTPException(status_code=404, detail="Source clip not found")
        
        clipper = StreamClipper("")
        success = clipper.trim_clip(
            input_path=str(input_path),
            output_path=str(output_path),
            start_time=trim_request.start_time,
            end_time=trim_request.end_time,
            quality=trim_request.quality
        )
        logger.info(f"Trimming clip quality: {trim_request.quality}")
        
        if success:
            logger.info(f"Clip trimmed successfully: {output_path}")
            return {"status": "success", "output_path": output_path.name}
        else:
            logger.error("Failed to trim clip")
            raise HTTPException(status_code=500, detail="Failed to trim clip")
            
    except Exception as e:
        logger.error(f"Error in trim_clip: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info(f"Static directory: {STATIC_DIR}")
    logger.info(f"Recordings directory: {RECORDINGS_DIR}")
    logger.info(f"Clips directory: {CLIPS_DIR}")
    uvicorn.run(app, host="127.0.0.1", port=8866)
