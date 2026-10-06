import os
import shutil
import subprocess
import sys
from pathlib import Path

# ================= CONFIGURATION =================
BASE_DIR = Path(__file__).resolve().parent
MODEL_NAME = "MyCustomVoice"
DATASET_PATH = (BASE_DIR / "cleaned_for_rvc").resolve()
LOGS_DIR = BASE_DIR / "logs" / MODEL_NAME

# Training Parameters
SAMPLE_RATE = "48000"
TOTAL_EPOCHS = "250"
BATCH_SIZE = "4"          # 4 is stable and prevents out-of-memory
SAVE_EVERY_EPOCH = "25"
PITCH_METHOD = "rmvpe"
EMBEDDER = "contentvec"
INCLUDE_MUTES = "2"
GPU_ID = "0"              # Use primary NVIDIA GPU

OUTPUT_EXPORT_DIR = BASE_DIR / "exported_models" / MODEL_NAME

PYTHON_EXE = str(BASE_DIR / "env" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = str(BASE_DIR / "env" / "Scripts" / "python.exe")
# =================================================

def run_step(step_name: str, cmd: list):
    print(f"\n{'='*20} [STEP] {step_name} {'='*20}")
    print(f"Command: {' '.join(cmd)}\n")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        print(f"\n[ERROR] Step '{step_name}' failed with exit code {res.returncode}.")
        sys.exit(res.returncode)

def main():
    if not DATASET_PATH.exists() or not any(DATASET_PATH.iterdir()):
        print(f"[ERROR] Cleaned dataset folder empty: {DATASET_PATH}")
        sys.exit(1)

    # 1. Dataset Preprocessing
    run_step(
        "1. Dataset Preprocessing",
        [
            PYTHON_EXE, "core.py", "preprocess",
            "--model_name", MODEL_NAME,
            "--dataset_path", str(DATASET_PATH),
            "--sample_rate", SAMPLE_RATE,
            "--cut_preprocess", "Automatic"
        ]
    )

    # 2. Feature Extraction (Enforce GPU 0 and proper core allocation)
    run_step(
        "2. Feature Extraction",
        [
            PYTHON_EXE, "core.py", "extract",
            "--model_name", MODEL_NAME,
            "--sample_rate", SAMPLE_RATE,
            "--f0_method", PITCH_METHOD,
            "--embedder_model", EMBEDDER,
            "--include_mutes", INCLUDE_MUTES,
            "--cpu_cores", "4",
            "--gpu", GPU_ID
        ]
    )

    # 3. Model Training
    run_step(
        "3. Neural Training",
        [
            PYTHON_EXE, "core.py", "train",
            "--model_name", MODEL_NAME,
            "--sample_rate", SAMPLE_RATE,
            "--total_epoch", TOTAL_EPOCHS,
            "--batch_size", BATCH_SIZE,
            "--save_every_epoch", SAVE_EVERY_EPOCH,
            "--save_every_weights", "True",
            "--gpu", GPU_ID
        ]
    )

    # 4. Building FAISS Index
    run_step(
        "4. Building FAISS Index",
        [
            PYTHON_EXE, "core.py", "index",
            "--model_name", MODEL_NAME
        ]
    )

    # 5. Export Artifacts
    print(f"\n{'='*20} [COMPLETED] Packaging Weights {'='*20}")
    OUTPUT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR = BASE_DIR / "models"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    pth_candidates = list(LOGS_DIR.glob(f"{MODEL_NAME}.pth")) or list(LOGS_DIR.glob(f"{MODEL_NAME}_*.pth"))
    
    # If no standalone inference .pth was created, extract from the latest G_*.pth checkpoint
    if not pth_candidates:
        g_checkpoints = sorted(
            list(LOGS_DIR.glob("G_*.pth")),
            key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0
        )
        if g_checkpoints:
            latest_g = g_checkpoints[-1]
            print(f"Extracting inference model from checkpoint: {latest_g.name}...")
            from rvc.train.process.extract_model import extract_model
            from rvc.configs.config import Config
            import torch
            
            ckpt = torch.load(latest_g, map_location="cpu")
            cfg_path = LOGS_DIR / "config.json"
            if cfg_path.exists():
                import json
                with open(cfg_path, "r", encoding="utf-8") as f:
                    hps_dict = json.load(f)
                from types import SimpleNamespace
                def dict_to_namespace(d):
                    if isinstance(d, dict):
                        return SimpleNamespace(**{k: dict_to_namespace(v) for k, v in d.items()})
                    return d
                hps = dict_to_namespace(hps_dict)
                dest = LOGS_DIR / f"{MODEL_NAME}.pth"
                extract_model(
                    ckpt=ckpt.get("weight", ckpt),
                    sr=int(SAMPLE_RATE),
                    name=MODEL_NAME,
                    model_path=str(dest),
                    epoch=int(TOTAL_EPOCHS),
                    step=int(latest_g.stem.split("_")[1]) if latest_g.stem.split("_")[1].isdigit() else 0,
                    hps=hps,
                    vocoder="HiFi-GAN",
                    pitch_guidance=True,
                    version="v2"
                )
                if dest.exists():
                    pth_candidates = [dest]

    index_candidates = list(LOGS_DIR.glob("*.index"))

    if pth_candidates:
        dest_pth = OUTPUT_EXPORT_DIR / f"{MODEL_NAME}.pth"
        shutil.copy2(pth_candidates[0], dest_pth)
        shutil.copy2(pth_candidates[0], MODELS_DIR / f"{MODEL_NAME}.pth")
        print(f" Saved Model Weights: {dest_pth}")
        print(f" Synced to Models Dir: {MODELS_DIR / f'{MODEL_NAME}.pth'}")
    else:
        print("[ERROR] No .pth file generated or found.")

    if index_candidates:
        dest_index = OUTPUT_EXPORT_DIR / f"{MODEL_NAME}.index"
        shutil.copy2(index_candidates[0], dest_index)
        shutil.copy2(index_candidates[0], MODELS_DIR / f"{MODEL_NAME}.index")
        print(f" Saved Search Index:  {dest_index}")
        print(f" Synced to Models Dir: {MODELS_DIR / f'{MODEL_NAME}.index'}")

if __name__ == "__main__":
    main()