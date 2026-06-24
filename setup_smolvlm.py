#!/usr/bin/env python3
"""
Download SmolVLM2-500M-Video-Instruct model locally
Run this script first before using video analysis
"""

import os
from transformers import AutoProcessor, AutoModelForImageTextToText

def download_smolvlm_model():
    """Download SmolVLM model to local directory"""
    
    model_name = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    local_path = "./models/SmolVLM2-500M-Video-Instruct"
    
    print("=" * 60)
    print("📥 DOWNLOADING SMOLVLM2-500M-VIDEO-INSTRUCT MODEL")
    print("=" * 60)
    print(f"Model: {model_name}")
    print(f"Local path: {local_path}")
    print("=" * 60)
    
    try:
        # Create models directory
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Download processor
        print("📝 Downloading processor...")
        processor = AutoProcessor.from_pretrained(model_name)
        processor.save_pretrained(local_path)
        print("✅ Processor downloaded")
        
        # Download model
        print("🤖 Downloading model (this may take a while)...")
        model = AutoModelForImageTextToText.from_pretrained(model_name)
        model.save_pretrained(local_path)
        print("✅ Model downloaded")
        
        print("=" * 60)
        print("🎉 SmolVLM model downloaded successfully!")
        print(f"📁 Location: {os.path.abspath(local_path)}")
        print("=" * 60)
        
        # Verify download
        if os.path.exists(local_path):
            files = os.listdir(local_path)
            print(f"📋 Downloaded files: {len(files)} files")
            for f in files[:5]:  # Show first 5 files
                print(f"   - {f}")
            if len(files) > 5:
                print(f"   ... and {len(files)-5} more files")
        
        return True
        
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False

def check_dependencies():
    """Check if required dependencies are installed"""
    print("🔍 Checking dependencies...")
    
    required_packages = [
        'transformers',
        'torch', 
        'yt-dlp',
        'langchain',
        'langchain-openai'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - NOT INSTALLED")
            missing_packages.append(package)
    
    if missing_packages:
        print("\n📦 Install missing packages:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ All dependencies are installed")
    return True

if __name__ == "__main__":
    print("🚀 Setting up SmolVLM Video Analysis")
    print()
    
    # Check dependencies first
    if not check_dependencies():
        print("⚠️ Please install missing dependencies first")
        exit(1)
    
    # Download model
    success = download_smolvlm_model()
    
    if success:
        print("\n🎬 Setup complete! You can now use video analysis.")
        print("\nNext steps:")
        print("1. Run: python test_video_routing.py")
        print("2. Or use the video agent in your workflow")
    else:
        print("\n❌ Setup failed. Please check error messages above.")
        exit(1)