#!/usr/bin/env python3
"""
VoiceOver Studio Web Application - Vercel Compatible Version
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import json
import numpy as np
from pathlib import Path
from datetime import datetime
import time
import asyncio
import wave
import sys
import subprocess
import os
import socket
from werkzeug.utils import secure_filename
import tempfile
import base64
import io

# Create Flask app
app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Configure directories for Vercel (use /tmp for writable storage)
if os.environ.get('VERCEL'):
    WORK_DIR = Path('/tmp/voiceover_projects')
else:
    WORK_DIR = Path("voiceover_projects")

WORK_DIR.mkdir(exist_ok=True, parents=True)
SPECIMENS_FILE = WORK_DIR / "specimens.json"
PROJECTS_FILE = WORK_DIR / "projects.json"
RECORDINGS_FILE = WORK_DIR / "recordings.json"

# Voice configurations
ELEVEN_VOICES = {
    "niraj": {
        "id": "zgqefOY5FPQ3bB7OZTVR",
        "name": "Niraj - Indian Urdu Voice",
        "display": "🇵🇰 Niraj - Natural Pakistani/Urdu accent",
        "style": "Warm, educational"
    },
    "ritika": {
        "id": "laI5NPLxoOASGAQ568u2",
        "name": "Ritika - Lively Survey Voice",
        "display": "🇵🇰 Ritika - Lively & Engaging",
        "style": "Energetic, friendly"
    }
}

# Free voices that definitely work with edge-tts
EDGE_VOICES = {
    "1": {
        "name": "en-IN-NeerjaNeural",
        "display": "🇮🇳 Indian Female (Neerja)",
        "style": "Clear, professional South Asian accent",
        "gender": "Female"
    },
    "2": {
        "name": "en-IN-PrabhatNeural",
        "display": "🇮🇳 Indian Male (Prabhat)",
        "style": "Authoritative South Asian accent",
        "gender": "Male"
    },
    "3": {
        "name": "en-US-JennyNeural",
        "display": "🇺🇸 US Female (Jenny)",
        "style": "Warm, natural American accent",
        "gender": "Female"
    },
    "4": {
        "name": "en-US-GuyNeural",
        "display": "🇺🇸 US Male (Guy)",
        "style": "Professional American accent",
        "gender": "Male"
    },
    "5": {
        "name": "en-GB-SoniaNeural",
        "display": "🇬🇧 UK Female (Sonia)",
        "style": "Elegant British accent",
        "gender": "Female"
    },
    "6": {
        "name": "en-AU-NatashaNeural",
        "display": "🇦🇺 Australian Female (Natasha)",
        "style": "Warm Australian accent",
        "gender": "Female"
    }
}

# Check available libraries
PYDUB_OK = False
SOUNDCARD_OK = False
EDGE_OK = False
ELEVEN_OK = False

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    pass

try:
    import soundcard as sc
    SOUNDCARD_OK = True
except ImportError:
    pass

try:
    import edge_tts
    EDGE_OK = True
except ImportError:
    pass

try:
    from elevenlabs import generate, set_api_key
    ELEVEN_OK = True
except ImportError:
    pass

# Global variables
eleven_enabled = False
eleven_api_key = None

# Custom JSON encoder
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)

app.json_encoder = NumpyEncoder

def load_json(filepath):
    if filepath.exists():
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def estimate_script_duration(script):
    """Estimate speaking duration in seconds"""
    word_count = len(script.split())
    if word_count > 0:
        seconds = word_count / 2.5
    else:
        seconds = len(script) / 15
    buffer = max(2, seconds * 0.1)
    return max(3, int(seconds + buffer))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/voices', methods=['GET'])
def get_voices():
    """Get available voices"""
    voices = {
        "premium": [],
        "free": []
    }
    
    if eleven_enabled:
        for key, voice in ELEVEN_VOICES.items():
            voices["premium"].append({
                "id": key,
                "name": voice["name"],
                "display": voice["display"],
                "style": voice["style"],
                "gender": voice.get("gender", "Unknown")
            })
    
    for key, voice in EDGE_VOICES.items():
        voices["free"].append({
            "id": key,
            "name": voice["name"],
            "display": voice["display"],
            "style": voice["style"],
            "gender": voice.get("gender", "Unknown")
        })
    
    return jsonify(voices)

@app.route('/api/configure_eleven', methods=['POST'])
def configure_eleven():
    global eleven_enabled, eleven_api_key
    
    data = request.json
    api_key = data.get('api_key', '')
    
    if api_key and ELEVEN_OK:
        try:
            set_api_key(api_key)
            eleven_api_key = api_key
            eleven_enabled = True
            return jsonify({"success": True, "message": "ElevenLabs configured successfully"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    else:
        return jsonify({"success": False, "message": "Invalid API key or ElevenLabs not installed"})

@app.route('/api/record', methods=['POST'])
def record_voice():
    """Record voice specimen"""
    data = request.json
    name = data.get('name', '')
    duration = float(data.get('duration', 5))
    
    if not name:
        return jsonify({"success": False, "message": "Name required"})
    
    if not SOUNDCARD_OK:
        return jsonify({"success": False, "message": "Soundcard not available. Recording requires a local environment."})
    
    try:
        mics = sc.all_microphones()
        if not mics:
            return jsonify({"success": False, "message": "No microphone found."})
        
        mic = sc.default_microphone()
        sample_rate = 44100
        recording = mic.record(samplerate=sample_rate, 
                              numframes=int(sample_rate * duration))
        
        if recording is None or len(recording) == 0:
            return jsonify({"success": False, "message": "No audio captured"})
        
        recordings_dir = WORK_DIR / "recordings"
        recordings_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = recordings_dir / f"{name}_{timestamp}.wav"
        
        audio_int16 = (recording * 32767).astype(np.int16)
        
        with wave.open(str(filename), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        
        rms = float(np.sqrt(np.mean(recording**2)))
        volume_db = float(20 * np.log10(rms + 0.0001))
        duration_float = float(len(recording) / sample_rate)
        
        recordings = load_json(RECORDINGS_FILE)
        if "self_recordings" not in recordings:
            recordings["self_recordings"] = []
        
        recording_entry = {
            "id": timestamp,
            "name": name,
            "file": str(filename),
            "duration": duration_float,
            "volume_db": round(volume_db, 1),
            "created": timestamp,
            "type": "self_recording"
        }
        recordings["self_recordings"].append(recording_entry)
        save_json(RECORDINGS_FILE, recordings)
        
        return jsonify({
            "success": True,
            "file": str(filename),
            "duration": duration_float,
            "volume_db": round(volume_db, 1),
            "recording_id": timestamp,
            "message": f"Recorded {duration_float:.1f} seconds"
        })
        
    except Exception as e:
        print(f"Recording error: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/recordings', methods=['GET'])
def get_recordings():
    recordings = load_json(RECORDINGS_FILE)
    return jsonify(recordings.get("self_recordings", []))

@app.route('/api/delete_recording', methods=['POST'])
def delete_recording():
    data = request.json
    recording_id = data.get('recording_id', '')
    
    if not recording_id:
        return jsonify({"success": False, "message": "Recording ID required"})
    
    recordings = load_json(RECORDINGS_FILE)
    
    if "self_recordings" in recordings:
        for i, rec in enumerate(recordings["self_recordings"]):
            if rec.get("id") == recording_id:
                file_path = Path(rec.get("file"))
                if file_path.exists():
                    file_path.unlink()
                recordings["self_recordings"].pop(i)
                save_json(RECORDINGS_FILE, recordings)
                return jsonify({"success": True, "message": "Recording deleted"})
    
    return jsonify({"success": False, "message": "Recording not found"})

@app.route('/api/generate', methods=['POST'])
def generate_voiceover():
    """Generate voiceover from script"""
    data = request.json
    script = data.get('script', '')
    project_name = data.get('project_name', '')
    voice_type = data.get('voice_type', 'free')
    voice_id = data.get('voice_id', '1')
    
    if not script:
        return jsonify({"success": False, "message": "Script is empty"})
    
    if not project_name:
        project_name = f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    project_name = secure_filename(project_name)
    estimated_duration = estimate_script_duration(script)
    
    project_dir = WORK_DIR / project_name
    project_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = project_dir / f"{project_name}_{timestamp}.mp3"
    
    try:
        if voice_type == 'premium' and eleven_enabled and ELEVEN_OK:
            voice_info = ELEVEN_VOICES.get(voice_id)
            if not voice_info:
                return jsonify({"success": False, "message": "Invalid voice ID"})
            
            audio = generate(
                text=script,
                voice=voice_info["id"],
                model="eleven_monolingual_v1"
            )
            
            with open(output_file, 'wb') as f:
                f.write(audio)
                
        else:
            # Use edge-tts (free)
            if not EDGE_OK:
                return jsonify({"success": False, "message": "Edge TTS not available. Please install edge-tts."})
            
            voice_info = EDGE_VOICES.get(voice_id, EDGE_VOICES["1"])
            
            async def generate_edge():
                communicate = edge_tts.Communicate(script, voice_info["name"])
                await communicate.save(str(output_file))
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(generate_edge())
            loop.close()
        
        if output_file.exists() and output_file.stat().st_size > 0:
            file_size = output_file.stat().st_size / 1024
            
            actual_duration = estimated_duration
            if PYDUB_OK:
                try:
                    audio = AudioSegment.from_mp3(output_file)
                    actual_duration = len(audio) / 1000
                except:
                    pass
            
            projects = load_json(PROJECTS_FILE)
            if project_name not in projects:
                projects[project_name] = []
            
            projects[project_name].append({
                "file": str(output_file),
                "script": script[:200],
                "voice": voice_info["display"],
                "created": timestamp,
                "duration": actual_duration
            })
            save_json(PROJECTS_FILE, projects)
            
            return jsonify({
                "success": True,
                "file": str(output_file),
                "file_name": output_file.name,
                "size_kb": round(file_size, 1),
                "duration_seconds": round(actual_duration, 1),
                "estimated_seconds": estimated_duration,
                "message": "Voiceover generated successfully"
            })
        else:
            return jsonify({"success": False, "message": "Generation failed"})
            
    except Exception as e:
        print(f"Generation error: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/projects', methods=['GET'])
def get_projects():
    projects = load_json(PROJECTS_FILE)
    return jsonify(projects)

@app.route('/api/specimens', methods=['GET'])
def get_specimens():
    specimens = load_json(SPECIMENS_FILE)
    return jsonify(specimens)

@app.route('/api/delete_voiceover', methods=['POST'])
def delete_voiceover():
    data = request.json
    project_name = data.get('project_name', '')
    file_index = data.get('file_index', None)
    
    if not project_name:
        return jsonify({"success": False, "message": "Project name required"})
    
    projects = load_json(PROJECTS_FILE)
    
    if project_name not in projects:
        return jsonify({"success": False, "message": "Project not found"})
    
    files = projects[project_name]
    
    if file_index is not None and 0 <= file_index < len(files):
        file_to_delete = files[file_index]
        file_path = Path(file_to_delete["file"])
        
        if file_path.exists():
            file_path.unlink()
        
        files.pop(file_index)
        
        if len(files) == 0:
            del projects[project_name]
            project_dir = WORK_DIR / project_name
            if project_dir.exists():
                import shutil
                shutil.rmtree(project_dir)
        else:
            projects[project_name] = files
        
        save_json(PROJECTS_FILE, projects)
        
        return jsonify({"success": True, "message": "Voiceover deleted successfully"})
    else:
        return jsonify({"success": False, "message": "Invalid file index"})

@app.route('/api/audio/<path:filepath>')
def serve_audio(filepath):
    try:
        return send_file(filepath, mimetype='audio/mpeg')
    except:
        return jsonify({"error": "File not found"}), 404

# This is the handler for Vercel
app.debug = False

# For local development
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "="*50)
    print("🎙️ VoiceOver Studio Web Application")
    print("="*50)
    print(f"\n✅ Server starting on port: {port}")
    print("\n" + "="*50 + "\n")
    
    app.run(debug=False, host='0.0.0.0', port=port)