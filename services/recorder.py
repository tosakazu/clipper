import subprocess
import os
import glob
import threading
import time
from typing import Optional
import logging
from datetime import datetime
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StreamRecorder:
    def __init__(self, url: str, base_dir: str, buffer_minutes: int = 10, quality: str = "best"):
        self.url = url
        self.base_dir = base_dir
        self.buffer_minutes = buffer_minutes
        self.quality = quality
        self.segments_dir = os.path.join(base_dir, "segments")
        self.is_recording = False
        self.stream_process: Optional[subprocess.Popen] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self.cleanup_thread: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.last_segment_time = time.time()
        self.logger = logging.getLogger(f'StreamRecorder-{base_dir}')
        
        # 既存のセグメントディレクトリを削除
        shutil.rmtree(self.segments_dir, ignore_errors=True)

        os.makedirs(self.segments_dir, exist_ok=True)

    def start(self) -> bool:
        if self.is_recording:
            self.logger.warning("Recording is already in progress")
            return False

        self.logger.info(f"Starting recording for URL: {self.url}")
        self.is_recording = True
        
        try:
            # streamlinkプロセスの開始
            # start メソッド内の streamlink_cmd を変更:
            streamlink_cmd = [
                "streamlink",
                "--stream-segment-threads", "4",
                "--loglevel", "debug",
                "--retry-max", "10",           # リトライ回数を増やす
                "--retry-streams", "60",       # ストリーム再試行の待機時間を60秒に
                "--stream-timeout", "60",      # ストリームタイムアウトを60秒に
                self.url,
                self.quality,
                "-O"
            ]
            self.stream_process = subprocess.Popen(
                streamlink_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.logger.info("Streamlink process started successfully")

            # ffmpegプロセスの開始
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-c", "copy",
                "-f", "segment",
                "-segment_time", "60",    # 1分ごとにセグメント
                "-segment_format", "mpegts",
                "-reset_timestamps", "1",
                os.path.join(self.segments_dir, "out%05d.ts")
            ]
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=self.stream_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.logger.info("FFmpeg process started successfully")

            # クリーンアップスレッドの開始
            self.cleanup_thread = threading.Thread(target=self._cleanup_old_segments)
            self.cleanup_thread.daemon = True
            self.cleanup_thread.start()

            # モニタリングスレッドの開始
            self.monitor_thread = threading.Thread(target=self._monitor_recording)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()

            return True

        except Exception as e:
            self.logger.error(f"Failed to start recording: {str(e)}")
            self.stop()
            return False

    def stop(self):
        self.logger.info("Stopping recording")
        self.is_recording = False
        
        if self.stream_process:
            self.stream_process.terminate()
            self.stream_process.wait()
            self.stream_process = None
            
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
            self.ffmpeg_process.wait()
            self.ffmpeg_process = None

        self.logger.info("Recording stopped successfully")

    def _cleanup_old_segments(self):
        while self.is_recording:
            try:
                # セグメントファイルの一覧を取得して古い順にソート
                segment_files = glob.glob(os.path.join(self.segments_dir, "out*.ts"))
                segment_files.sort()
                
                # バッファサイズを超えているか確認
                if len(segment_files) > self.buffer_minutes:
                    files_to_remove = segment_files[:-self.buffer_minutes]
                    for f in files_to_remove:
                        try:
                            os.remove(f)
                            self.logger.debug(f"Removed old segment: {f}")
                        except OSError as e:
                            self.logger.error(f"Error removing file {f}: {e}")
            except Exception as e:
                self.logger.error(f"Error in cleanup thread: {e}")
            
            # 10秒待機
            time.sleep(10)

    def _monitor_recording(self):
        error_count = 0
        while self.is_recording:
            try:
                # プロセスチェック
                if self.stream_process and self.stream_process.poll() is not None:
                    self.logger.warning("Streamlink process ended - waiting before restart")
                    time.sleep(10)  # 少し待機してから再起動
                    self._restart_recording()
                    continue

                # セグメントファイルのチェック
                segment_files = glob.glob(os.path.join(self.segments_dir, "out*.ts"))
                if segment_files:
                    latest_file = max(segment_files, key=os.path.getmtime)
                    current_time = time.time()
                    last_modified = os.path.getmtime(latest_file)
                    
                    if current_time - last_modified > 180:  # 3分に延長
                        self.logger.warning("No new segments - but waiting longer before restart")
                        error_count += 1
                        if error_count >= 3:  # 3回連続でタイムアウトしたら再起動
                            self.logger.info("Attempting restart after multiple timeouts")
                            self._restart_recording()
                            error_count = 0
                    else:
                        error_count = 0

                # プロセスの出力をチェック
                if self.stream_process and self.stream_process.stderr:
                    stderr_line = self.stream_process.stderr.readline().decode().strip()
                    if stderr_line:
                        self.logger.debug(f"Streamlink output: {stderr_line}")

                if self.ffmpeg_process and self.ffmpeg_process.stderr:
                    stderr_line = self.ffmpeg_process.stderr.readline().decode().strip()
                    if stderr_line:
                        self.logger.debug(f"FFmpeg output: {stderr_line}")

            except Exception as e:
                self.logger.error(f"Error in monitoring thread: {e}")

            time.sleep(5)

    def _restart_recording(self):
        """録画プロセスを再起動"""
        self.logger.info("Attempting to restart recording")
        try:
            # 既存のプロセスを停止
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                try:
                    self.ffmpeg_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.ffmpeg_process.kill()

            if self.stream_process:
                self.stream_process.terminate()
                try:
                    self.stream_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.stream_process.kill()

            # start メソッドと同じコマンドで再起動
            streamlink_cmd = [
                "streamlink",
                "--stream-segment-threads", "4",
                "--loglevel", "debug",
                "--retry-max", "10",
                "--retry-streams", "60",
                "--stream-timeout", "60",
                self.url,
                self.quality,
                "-O"
            ]
            
            self.stream_process = subprocess.Popen(
                streamlink_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-c", "copy",
                "-f", "segment",
                "-segment_time", "60",
                "-segment_format", "mpegts",
                "-reset_timestamps", "1",
                os.path.join(self.segments_dir, "out%05d.ts")
            ]
            
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=self.stream_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            self.logger.info("Recording successfully restarted")
            
        except Exception as e:
            self.logger.error(f"Failed to restart recording: {e}")

    def get_status(self) -> dict:
        """録画の状態を取得"""
        try:
            segment_files = glob.glob(os.path.join(self.segments_dir, "out*.ts"))
            total_size = sum(os.path.getsize(f) for f in segment_files if os.path.exists(f))
            latest_time = max(os.path.getmtime(f) for f in segment_files) if segment_files else None
            
            return {
                "is_recording": self.is_recording,
                "segment_count": len(segment_files),
                "total_size_mb": total_size / (1024 * 1024),
                "last_segment_time": datetime.fromtimestamp(latest_time).isoformat() if latest_time else None
            }
        except Exception as e:
            self.logger.error(f"Error getting status: {e}")
            return {
                "is_recording": self.is_recording,
                "segment_count": 0,
                "total_size_mb": 0,
                "last_segment_time": None
            }