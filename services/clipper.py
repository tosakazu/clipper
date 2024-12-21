import os
import glob
import subprocess
import logging
from typing import List
from pathlib import Path
import uuid
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StreamClipper:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.segments_dir = os.path.join(base_dir, "segments") if base_dir else ""

    def create_clip(self, duration: int, output_path: str) -> bool:
        """
        最新のn分間のセグメントからクリップを作成
        """
        try:
            duration += 1  # 最新のセグメントは1分に満たないことがあるので+1個しておく
            logger.info(f"Starting clip creation from: {self.segments_dir}")
            if not self.segments_dir or not os.path.exists(self.segments_dir):
                logger.error(f"Segments directory does not exist: {self.segments_dir}")
                return False

            # セグメントファイルの取得
            segment_files = glob.glob(os.path.join(self.segments_dir, "out*.ts"))
            segment_files.sort()
            logger.info(f"Found {len(segment_files)} segment files")

            if len(segment_files) < duration:
                logger.error(f"Not enough segments: found {len(segment_files)}, need {duration}")
                return False

            # 必要なセグメントの選択
            segments_to_use = segment_files[-duration:]
            logger.info(f"Using {len(segments_to_use)} segments for clip")

            # 連結リストファイルの作成
            concat_list = os.path.join(self.base_dir, "concat_list.txt")
            with open(concat_list, "w") as f:
                for seg in segments_to_use:
                    f.write(f"file '{seg}'\n")

            logger.info(f"Created concat list at: {concat_list}")

            temp_output = f"temp_output_{uuid.uuid4().hex}.ts"

            # FFmpegで連結
            concat_cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                temp_output
            ]
            logger.info(f"Running FFmpeg command: {' '.join(concat_cmd)}")
            result = subprocess.run(concat_cmd, check=True)

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            # 連結後の動画の長さを取得
            total_duration = self.get_video_duration(temp_output)
            trim_seconds = (duration - 1) * 60 # 最初に+1しているので-1する
            if total_duration <= trim_seconds:
                raise ValueError("Trim duration is longer than or equal to the total duration of the video.")

            # 切り抜き範囲を計算
            start_time = total_duration - trim_seconds

            # FFmpegで切り抜き
            trim_cmd = [
                "ffmpeg",
                "-y",
                "-i", temp_output,
                "-ss", f"{start_time:.2f}",
                "-c", "copy",
                output_path
            ]
            logger.info(f"Running FFmpeg command: {' '.join(trim_cmd)}")
            result = subprocess.run(trim_cmd, check=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            # 一時ファイルを削除（必要に応じて）
            subprocess.run(["rm", temp_output])

            if result.returncode != 0:
                logger.error(f"rm error: {result.stderr}")
                return False

            logger.info(f"Successfully created clip at: {output_path}")
            
            # 一時ファイルの削除
            if os.path.exists(concat_list):
                os.remove(concat_list)
                logger.info("Cleaned up concat list file")

            return True

        except Exception as e:
            logger.error(f"Error in create_clip: {str(e)}")
            return False

    def trim_clip(self, input_path: str, output_path: str, 
             start_time: float, end_time: float,
             quality: str = None) -> bool:
        """
        クリップから指定した部分を切り出し
        """
        try:
            duration = end_time - start_time
            
            # 画質設定に基づいてFFmpegコマンドを構築
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", input_path,
                "-t", str(duration),
            ]

            logger.info("quality: " + quality)

            # 画質設定が指定されている場合、エンコード設定を追加
            if quality and quality != "default":
                height = quality.replace("p", "")
                cmd.extend([
                    "-vf", f"scale=-2:{height}",  # -1 から -2 に変更
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "23",
                    "-c:a", "aac",
                ])
            else:
                cmd.extend(["-c", "copy"])  # 画質設定なしの場合はストリームコピー

            cmd.append(output_path)

            logger.info(f"Running trim command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg trim error: {result.stderr}")
                return False

            logger.info(f"Successfully trimmed clip to: {output_path}")
            
            # トリミング情報をJSONLファイルに保存
            json_path = Path(input_path).with_suffix('.jsonl')
            trim_info = {
                'timestamp': datetime.now().isoformat(),
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'quality': quality,
                'input_file': os.path.basename(input_path),
                'output_file': os.path.basename(output_path)
            }
            
            # JSONLファイルに追記
            with open(json_path, 'a', encoding='utf-8') as f:
                json.dump(trim_info, f, ensure_ascii=False)
                f.write('\n')
            
            logger.info(f"Trim information saved to: {json_path}")
            return True

        except Exception as e:
            logger.error(f"Error in trim_clip: {str(e)}")
            return False

    def get_video_duration(self, video_path: str) -> float:
        """
        動画の長さを取得（秒）
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout)
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"Error getting video duration: {str(e)}")
            return 0.0