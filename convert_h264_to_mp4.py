import subprocess
import sys
import os
import shutil
import tkinter as tk
from tkinter import filedialog

def check_ffmpeg():
    """Check if ffmpeg is installed and accessible."""
    if shutil.which("ffmpeg") is None:
        print("Error: ffmpeg is not installed or not in the system PATH.")
        print("Please install ffmpeg to use this script.")
        print("Download link: https://ffmpeg.org/download.html")
        return False
    return True

def convert_h264_to_mp4(input_file, output_file):
    """Converts an H.264 video file to MP4 format using ffmpeg."""
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        return

    # Basic command to copy the video stream into an mp4 container
    # -r 30 forces the input to be treated as 30 fps (matching default camera config)
    # -i input input file
    # -c copy copies the bitstream without re-encoding (fast and lossless)
    command = ['ffmpeg', '-r', '30', '-i', input_file, '-c', 'copy', output_file]

    try:
        print(f"Converting '{input_file}' to '{output_file}'...")
        subprocess.run(command, check=True)
        print("Conversion successful!")
        
        # Delete the original h264 file
        try:
            os.remove(input_file)
            print(f"Deleted original file: '{input_file}'")
        except Exception as e:
            print(f"Error deleting original file: {e}")

    except subprocess.CalledProcessError as e:
        print(f"Error during conversion: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    if not check_ffmpeg():
        sys.exit(1)

    input_path = ""
    output_path = ""

    # Support for simple usage: script.py input_file [output_file]
    if len(sys.argv) >= 2:
        input_path = sys.argv[1]
        if len(sys.argv) >= 3:
            output_path = sys.argv[2]
            
        if os.path.isfile(input_path):
            # Single file mode
            if not output_path:
                base, ext = os.path.splitext(input_path)
                output_path = base + ".mp4"
            convert_h264_to_mp4(input_path, output_path)
            sys.exit(0)
            
        target_path = input_path # It was a directory

    else:
        print("Opening folder selector...")
        root = tk.Tk()
        root.withdraw()
        # Ask for a directory
        target_path = filedialog.askdirectory(title="Select Folder containing H.264 Videos")

    if not target_path:
        print("No folder selected.")
        sys.exit(0)

    # If we reached here, target_path is either a directory or invalid path
    # (File case handled above)

    if os.path.isdir(target_path):
        # Directory mode
        print(f"Scanning '{target_path}' for .h264 files...")
        count = 0
        for root_dir, dirs, files in os.walk(target_path):
            for filename in files:
                if filename.lower().endswith(".h264"):
                    file_path = os.path.join(root_dir, filename)
                    base, _ = os.path.splitext(file_path)
                    output_file_path = base + ".mp4"
                    
                    # Optional: skip if output already exists to avoid overwriting/re-doing
                    # if os.path.exists(output_path):
                    #     continue

                    convert_h264_to_mp4(file_path, output_file_path)
                    count += 1
        
        if count == 0:
            print("No .h264 files found in the selected folder.")
        else:
            print(f"Done! Processed {count} files.")
    else:
        print(f"Error: Path '{target_path}' does not exist.")
