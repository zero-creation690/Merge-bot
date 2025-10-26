import subprocess
import asyncio
import logging

logger = logging.getLogger(__name__)

def get_video_duration(file_path: str) -> float:
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get video duration: {e}")
    return 0.0

async def burn_subtitles(video_path: str, sub_path: str, output_path: str):
    safe_sub_path = sub_path.replace("'", "'\\''")
    vf_filter = f"subtitles=filename='{safe_sub_path}':charenc=UTF-8:force_style='FontName=FreeSans,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,SecondaryColour=&H00000000'"
    
    cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel', 'error',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'superfast',
        '-crf', '24',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        '-threads', '0',
        '-y',
        output_path
    ]
    
    logger.info(f"Starting ffmpeg with command: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    await process.wait()
    
    if process.returncode != 0:
        stderr_output = await process.stderr.read()
        error_text = stderr_output.decode('utf-8', errors='ignore')
        raise Exception(f"FFmpeg failed: {error_text[:200]}")
    
    return True
