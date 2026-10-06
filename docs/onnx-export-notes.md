\# Real-Time Custom Voice Conversion Pipeline: RVC to ONNX



\## Project Overview

The goal of this project is to train a custom Retrieval-based Voice Conversion (RVC v2) model and export it from its legacy PyTorch checkpoint format (`.pth`) into a highly optimized ONNX graph (`.onnx`). The resulting ONNX model is designed to be deployed in a lightweight, low-latency Python system tray application (`voice\_tray\_app.py`) for real-time speech-to-speech conversion, bypassing the heavy overhead of standard PyTorch inference.



\## Technologies Used

\*   \*\*Applio (RVC Fork):\*\* Framework for audio preprocessing, feature extraction, and neural network training.

\*   \*\*PyTorch (2.1+):\*\* Deep learning backend used for training and model tracing.

\*   \*\*ONNX \& ONNX Runtime:\*\* Target framework for high-speed, low-latency hardware-agnostic inference.

\*   \*\*Hugging Face Hub:\*\* Repository for fetching foundation models (`rmvpe.pt`, `f0G48k.pth`, `f0D48k.pth`).

\*   \*\*Python 3.x:\*\* Core scripting and application environment.

\*   \*\*FAISS:\*\* Vector database used for generating the `.index` file to maintain voice accent and tone accuracy.



\---



\## Phase 1: Environment \& Foundation Model Setup

Training an RVC model requires specific pre-trained foundation weights. Initial training attempts failed instantly because the local environment lacked these foundational models, causing pitch extraction to silently fail and the dataset to appear "empty."



\*\*Resolution:\*\*

A script was executed to pull the necessary base weights directly from Hugging Face into the Applio directory structure:

1\.  `rmvpe.pt` (Robust pitch extractor) -> `assets/rmvpe/`

2\.  `f0G48k.pth` (HiFi-GAN Generator base) -> `assets/pretrained\_v2/`

3\.  `f0D48k.pth` (HiFi-GAN Discriminator base) -> `assets/pretrained\_v2/`



\---



\## Phase 2: Data Processing \& Neural Training

With the foundation models in place, the dataset was processed using Applio's headless `core.py` CLI.



1\.  \*\*Preprocessing:\*\* Sliced the raw audio dataset into chunks and normalized the sample rate to 48kHz.

2\.  \*\*Feature Extraction:\*\* Utilized RMVPE for pitch extraction and ContentVec (v2, 768 features) to extract audio embeddings across the sliced dataset.

3\.  \*\*Training:\*\* Trained the Generative Adversarial Network (GAN). The model saved checkpoints every 25 epochs.

4\.  \*\*Index Generation:\*\* Built a FAISS index from the extracted features to assist the model in reproducing the specific vocal timbre during inference.



\*Note: To extract a usable inference model midway through training, a missing `assets/config.json` file was restored, allowing the compiler to strip optimizer/discriminator states from the raw epoch weights (e.g., `G\_27275.pth`).\*



\---



\## Phase 3: The ONNX Export Challenge

Exporting the legacy RVC architecture to ONNX in modern PyTorch (2.1+) presented severe compatibility issues due to PyTorch's updated Dynamo and TorchScript tracing engines.



\### The Hurdles

1\.  \*\*Missing Dependencies:\*\* PyTorch required `onnxscript` to compile the graph, which had to be installed manually.

2\.  \*\*Config Type Anomalies:\*\* The internal checkpoint config contained string values for numerical parameters (e.g., `"1"` for dropout), causing PyTorch's `nn.Module` instantiation to crash.

3\.  \*\*Architecture Mismatches:\*\* Initial export attempts accidentally utilized a 40kHz architecture shape (`\[16, 16, 4, 4]`) against 48kHz weights (`\[24, 20, 4, 4]`), causing dimension mismatches.

4\.  \*\*Dynamo Shape Guards (`GuardOnDataDependentSymNode`):\*\* PyTorch's default exporter failed because a mathematical operation in RVC's residual blocks (`fused\_add\_tanh\_sigmoid\_multiply`) dynamically sliced tensors based on varying channel counts, which ONNX cannot trace dynamically.

5\.  \*\*TorchScript Legacy Bugs:\*\* Attempting to fall back to `torch.jit.trace` failed due to strict Python parsing rules. TorchScript crashed when encountering boolean evaluations of `nn.Embedding` modules and dynamic tuple unpacking in `attentions.py`.



\### The Solution

The final breakthrough involved a three-part strategy to bypass PyTorch's strict tracing constraints without permanently modifying the core Applio source code:

1\.  \*\*Hardcoded 48kHz Architecture:\*\* Bypassed the corrupt `.pth` config array entirely by explicitly defining the exact 17-parameter config required for RVC v2 48kHz.

2\.  \*\*Runtime Monkey-Patching:\*\* Dynamically patched `fused\_add\_tanh\_sigmoid\_multiply` in memory to use `torch.chunk(in\_act, 2, dim=1)`. This replaced the ambiguous tensor slice with a statically traceable ONNX operation.

3\.  \*\*Static Dummy Inputs:\*\* Removed the `dynamic\_axes` parameter from the export call. ONNX Runtime natively supports variable-length inputs during actual inference, so providing a static 500-frame dummy tensor during export successfully bypassed PyTorch's Dynamo complaints.



\---



\## Phase 4: The Final Export Script

This script encapsulates the final, successful logic to map the `.pth` weights to the patched architecture and export the `.onnx` graph.



```python

import sys

import os

from pathlib import Path

import torch

import torch.nn as nn



BASE\_DIR = Path(\_\_file\_\_).resolve().parent

if str(BASE\_DIR) not in sys.path:

&#x20;   sys.path.insert(0, str(BASE\_DIR))



\# Configuration

MODEL\_NAME = "MyCustomVoice"

PTH\_PATH = BASE\_DIR / "exported\_models" / MODEL\_NAME / f"{MODEL\_NAME}.pth"

ONNX\_OUTPUT\_PATH = BASE\_DIR / "exported\_models" / MODEL\_NAME / f"{MODEL\_NAME}.onnx"

TARGET\_SR = 48000

USE\_F0 = True



\# Runtime Patch for ONNX Shape Tracing

import rvc.lib.algorithm.commons as commons



def patched\_fused\_add\_tanh\_sigmoid\_multiply(input\_a, input\_b, n\_channels):

&#x20;   in\_act = input\_a + input\_b

&#x20;   t\_act, s\_act = torch.chunk(in\_act, 2, dim=1)

&#x20;   return torch.tanh(t\_act) \* torch.sigmoid(s\_act)



commons.fused\_add\_tanh\_sigmoid\_multiply = patched\_fused\_add\_tanh\_sigmoid\_multiply



\# Model Setup

from rvc.lib.algorithm.synthesizers import Synthesizer



class ONNXExportWrapper(nn.Module):

&#x20;   def \_\_init\_\_(self, net\_g):

&#x20;       super().\_\_init\_\_()

&#x20;       self.net\_g = net\_g



&#x20;   def forward(self, phone, phone\_lengths, pitch, pitchf, ds):

&#x20;       if hasattr(self.net\_g, "infer"):

&#x20;           return self.net\_g.infer(phone, phone\_lengths, pitch, pitchf, ds)

&#x20;       return self.net\_g(phone, phone\_lengths, pitch, pitchf, ds)



def main():

&#x20;   checkpoint = torch.load(PTH\_PATH, map\_location="cpu")

&#x20;   

&#x20;   # Strict 48kHz RVC v2 Configuration

&#x20;   config\_48k = \[

&#x20;       1025, 32, 192, 192, 768, 2, 6, 3, 0.0, "1",

&#x20;       \[3, 7, 11],

&#x20;       \[\[1, 3, 5], \[1, 3, 5], \[1, 3, 5]],

&#x20;       \[12, 10, 2, 2],

&#x20;       512,

&#x20;       \[24, 20, 4, 4],

&#x20;       109,

&#x20;       256

&#x20;   ]



&#x20;   net\_g = Synthesizer(\*config\_48k, TARGET\_SR, USE\_F0)



&#x20;   weights = checkpoint.get("weight", checkpoint)

&#x20;   cleaned\_weights = {

&#x20;       k.replace("module.", ""): v

&#x20;       for k, v in weights.items()

&#x20;       if not k.startswith("enc\_q")

&#x20;   }



&#x20;   net\_g.load\_state\_dict(cleaned\_weights, strict=False)

&#x20;   net\_g.eval()



&#x20;   export\_module = ONNXExportWrapper(net\_g)



&#x20;   # Static Dummy Inputs (Bypasses Dynamo Shape Guards)

&#x20;   test\_len = 500

&#x20;   dummy\_phone = torch.rand(1, test\_len, 768, dtype=torch.float32)

&#x20;   dummy\_lengths = torch.tensor(\[test\_len], dtype=torch.int64)

&#x20;   dummy\_pitch = torch.randint(1, 100, (1, test\_len), dtype=torch.int64)

&#x20;   dummy\_pitchf = torch.rand(1, test\_len, dtype=torch.float32)

&#x20;   dummy\_ds = torch.tensor(\[0], dtype=torch.int64)



&#x20;   dummy\_inputs = (dummy\_phone, dummy\_lengths, dummy\_pitch, dummy\_pitchf, dummy\_ds)



&#x20;   ONNX\_OUTPUT\_PATH.parent.mkdir(parents=True, exist\_ok=True)



&#x20;   with torch.no\_grad():

&#x20;       torch.onnx.export(

&#x20;           export\_module,

&#x20;           dummy\_inputs,

&#x20;           str(ONNX\_OUTPUT\_PATH),

&#x20;           export\_params=True,

&#x20;           opset\_version=16,

&#x20;           do\_constant\_folding=True,

&#x20;           input\_names=\["phone", "phone\_lengths", "pitch", "pitchf", "ds"],

&#x20;           output\_names=\["audio"]

&#x20;       )



if \_\_name\_\_ == "\_\_main\_\_":

&#x20;   main()

