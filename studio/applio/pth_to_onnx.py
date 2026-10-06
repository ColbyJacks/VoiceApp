import sys
import os
from pathlib import Path
import torch
import torch.nn as nn

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ================= CONFIGURATION =================
MODEL_NAME = "MyCustomVoice"
PTH_PATH = BASE_DIR / "exported_models" / MODEL_NAME / f"{MODEL_NAME}.pth"
ONNX_OUTPUT_PATH = BASE_DIR / "exported_models" / MODEL_NAME / f"{MODEL_NAME}.onnx"
TARGET_SR = 48000
USE_F0 = True
# =================================================

# ================= RUNTIME PATCH =================
import rvc.lib.algorithm.commons as commons

# This single patch ensures PyTorch doesn't try to dynamically slice
# based on varying channel counts during the graph export.
def patched_fused_add_tanh_sigmoid_multiply(input_a, input_b, n_channels):
    in_act = input_a + input_b
    t_act, s_act = torch.chunk(in_act, 2, dim=1)
    return torch.tanh(t_act) * torch.sigmoid(s_act)

commons.fused_add_tanh_sigmoid_multiply = patched_fused_add_tanh_sigmoid_multiply
# =================================================

from rvc.lib.algorithm.synthesizers import Synthesizer

class ONNXExportWrapper(nn.Module):
    def __init__(self, net_g):
        super().__init__()
        self.net_g = net_g

    def forward(self, phone, phone_lengths, pitch, pitchf, ds):
        if hasattr(self.net_g, "infer"):
            return self.net_g.infer(phone, phone_lengths, pitch, pitchf, ds)
        return self.net_g(phone, phone_lengths, pitch, pitchf, ds)

def main():
    if not PTH_PATH.exists():
        print(f"[ERROR] Could not find checkpoint at: {PTH_PATH}")
        sys.exit(1)

    print(f"Loading checkpoint: {PTH_PATH}")
    checkpoint = torch.load(PTH_PATH, map_location="cpu")
    version = checkpoint.get("version", "v2")

    config_48k = [
        1025, 32, 192, 192, 768, 2, 6, 3, 0.0, "1",
        [3, 7, 11],
        [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
        [12, 10, 2, 2],
        512,
        [24, 20, 4, 4],
        109,
        256
    ]

    print(f"Instantiating Synthesizer with strict 48kHz architecture (version={version})...")
    net_g = Synthesizer(*config_48k, TARGET_SR, USE_F0)

    weights = checkpoint.get("weight", checkpoint)
    cleaned_weights = {
        k.replace("module.", ""): v
        for k, v in weights.items()
        if not k.startswith("enc_q")
    }

    net_g.load_state_dict(cleaned_weights, strict=False)
    net_g.eval()

    export_module = ONNXExportWrapper(net_g)

    feats = 768 if version == "v2" else 256
    # We use a static frame count (e.g. 500 frames ~ 10 seconds)
    # The ONNX runtime will still accept variable inputs later.
    test_len = 500

    dummy_phone = torch.rand(1, test_len, feats, dtype=torch.float32)
    dummy_lengths = torch.tensor([test_len], dtype=torch.int64)
    dummy_pitch = torch.randint(1, 100, (1, test_len), dtype=torch.int64)
    dummy_pitchf = torch.rand(1, test_len, dtype=torch.float32)
    dummy_ds = torch.tensor([0], dtype=torch.int64)

    dummy_inputs = (dummy_phone, dummy_lengths, dummy_pitch, dummy_pitchf, dummy_ds)

    ONNX_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Exporting ONNX graph to: {ONNX_OUTPUT_PATH} ...")

    with torch.no_grad():
        # Export cleanly without Dynamo dynamic shape tracking
        torch.onnx.export(
            export_module,
            dummy_inputs,
            str(ONNX_OUTPUT_PATH),
            export_params=True,
            opset_version=16,
            do_constant_folding=True,
            input_names=["phone", "phone_lengths", "pitch", "pitchf", "ds"],
            output_names=["audio"]
            # Notice: dynamic_axes is completely removed
        )

    MODELS_DIR = BASE_DIR / "models"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    if ONNX_OUTPUT_PATH.exists():
        shutil.copy2(ONNX_OUTPUT_PATH, MODELS_DIR / ONNX_OUTPUT_PATH.name)
    data_file = ONNX_OUTPUT_PATH.parent / f"{ONNX_OUTPUT_PATH.name}.data"
    if data_file.exists():
        shutil.copy2(data_file, MODELS_DIR / data_file.name)

    print(f"\n[SUCCESS] Model successfully exported to ONNX:")
    print(f"  {ONNX_OUTPUT_PATH}")
    print(f"  Synced to: {MODELS_DIR / ONNX_OUTPUT_PATH.name}")

if __name__ == "__main__":
    main()