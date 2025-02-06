import os
import subprocess
from tqdm import tqdm
import logging
import tempfile
from multiprocessing import Pool
from functools import partial


logging.basicConfig(filename=r"D:\flac2opus.log", filemode="a", encoding='utf-8', format="%(asctime)s [%(levelname)s]: %(message)s", datefmt="%Y/%m/%d %H:%M:%S", level=logging.WARNING)


def detect_format(file):
    """检测文件格式"""

    with open(file, "rb") as f:
        header = f.read(4)

        if header[:4] == b"fLaC":
            return "flac"
        if header[:3] == b"ID3" or header[:2] in {b"\xFF\xFB", b"\xFF\xF3", b"\xFF\xF2"}:
            return "mp3"

    return None

def flac2wav(flac, wav):
    """将flac转换为wav 提取元数据和封面"""

    cover = os.path.splitext(wav)[0] + "_cover"
    result = subprocess.run([
        "ffmpeg", "-i", flac, "-map", "0:v", "-f", "image2", cover
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        cover = None

    metadata = os.path.splitext(wav)[0] + "_metadata.txt"
    subprocess.run([
        "ffmpeg", "-i", flac, "-f", "ffmetadata", metadata
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # stderr=subprocess.DEVNULL
    subprocess.run([
        "ffmpeg", "-i", flac, wav
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    return cover, metadata

def resample(wav):
    """sox高品质重采样"""

    vol = 0.0
    clip_err = ""
    name = os.path.splitext(os.path.basename(wav))[0] # 输入文件名（不带扩展名）
    directory = os.path.dirname(wav)
    temp_file = os.path.join(directory, f"{name}_48khz.wav")
    temp_dir = tempfile.mkdtemp(dir=r"D:\tmp") # 创建进程专用的临时目录

    try:
        result = subprocess.run([
            "sox_ng", "--temp", temp_dir, "--multi-threaded", "-G", wav, "-b", "16", temp_file, "rate", "-v", "-I", "-b", "97","48000", "dither", "-s"
            ], stderr=subprocess.PIPE, text=True, check=True)
        
        if result.stderr and not "decrease volume?" in result.stderr:
            logging.warning("'" + name + "' -> " + result.stderr)
            
        while "decrease volume?" in result.stderr:
            if vol > -1.8:
                vol -= 0.2
                vol = round(vol, 1)
            else:
                logging.warning("'" + name + "' still clipped at vol -1.8dB. bad record!")
                clip_err = " " + result.stderr
                break

            logging.warning("'" + name + "' -> " + result.stderr + " vol = " + f"{vol:.1f}dB")

            os.remove(temp_file)
            
            result = subprocess.run([
                "sox_ng", "--temp", temp_dir, "--multi-threaded", "-G", wav, "-b", "16", temp_file, "vol", f"{vol:.1f}dB", "rate", "-v", "-I", "-b", "97","48000", "dither", "-s"
                ], stderr=subprocess.PIPE, text=True, check=True)
    finally:
        for filename in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, filename))
            except: pass
        try:
            os.rmdir(temp_dir)
        except: pass

    os.replace(temp_file, os.path.join(directory, f"{name}.wav"))
    return vol, clip_err

def wav2opus(wav, cover=None, metadata=None, vol=0.0, clip_err=""):
    """将wav转换为opus 嵌入元数据和封面"""

    name = os.path.splitext(os.path.basename(wav))[0]
    directory = os.path.dirname(wav)
    opus = os.path.join(directory, f"{name}.opus")

    comments = []
    dict = {
    'track': 'TRACKNUMBER',
    'organization': 'ORGANIZATION',
    'version': 'VERSION',
    'performer': 'PERFORMER',
    'copyright': 'COPYRIGHT',
    'license': 'LICENSE',
    'description': 'DESCRIPTION',
    'disk': 'DISKNUMBER'
    }
    with open(metadata, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                key = key.strip().lower()

                if key in {'comment', 'encoder'}:
                    continue
                
                key = dict.get(key, key.upper()) # 字典的 get(key, default) 方法用于安全获取值

                comments.extend(["--comment", f"{key}={value}"])
    description = "auto gain(-G)." + (f" vol {vol:.1f}dB." if vol != 0.0 else "") + clip_err
    comments.extend(["--comment", f"DESCRIPTION={description}"])

    cmd = [
        "opusenc", "--vbr", "--bitrate", "320", "--comp", "10", "--framesize", "20", "--music"
        ]
    if cover:
        cmd += ["--picture", cover]
    cmd += comments + [wav, opus]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    os.remove(wav)
    if cover:
        os.remove(cover)
    if metadata:
        os.remove(metadata)

def convert(file, path):
    """处理单个文件的工作函数"""

    try:
        file_path = os.path.join(path, file)
        output_dir = os.path.join(path, "wav")
        name = os.path.splitext(os.path.basename(file_path))[0]
        temp_file = os.path.join(output_dir, f"{name}.wav")

        cover, metadata = flac2wav(file_path, temp_file)
        vol, clip_err = resample(temp_file)
        wav2opus(temp_file, cover, metadata, vol, clip_err)
    except Exception as e:
        logging.error(f"converting '{file}' Failed: {str(e)}")
        raise

if __name__ == "__main__":
    path = r"D:\[170404~250119]我喜欢的音乐"
    output_dir = os.path.join(path, "wav")
    os.makedirs(output_dir, exist_ok=True)

    # 创建任务列表
    files = []
    for file in os.listdir(path):
        file_path = os.path.join(path, file)
        if os.path.isfile(file_path) and detect_format(file_path) == "flac":
            files.append(file)

    # 创建进程池并行处理
    with Pool(processes=2) as pool:
        processor = partial(convert, path=path)
        list(tqdm(pool.imap(processor, files), total=len(files)))
