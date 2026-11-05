# 來源與致謝

公開包只包含 Banana MV 整合程式、工作流與測試，不包含模型權重、第三方儲存庫、下載指南內容或使用者素材。

| 元件 | 來源 |
| --- | --- |
| ComfyUI | https://github.com/Comfy-Org/ComfyUI |
| MiniMax H3 Audio T8 節點 | https://github.com/T8mars/comfyui-minimax-h3-audio-T8 |
| MiniMax H3 與參考指南 | https://huggingface.co/MiniMaxAI/MiniMax-H3 |
| H3 PRISM 底模 | https://huggingface.co/OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM |
| Comfy 編碼器與 VAE | https://huggingface.co/Comfy-Org/MiniMax-H3 |
| 9B 改寫模型與動作 LoRA | https://huggingface.co/dseditor/minimax-h3-studio-assets |
| PyTorch | https://pytorch.org/ |
| Hugging Face Hub | https://github.com/huggingface/huggingface_hub |
| FFmpeg | https://ffmpeg.org/ |
| Pillow、NumPy、ipywidgets | https://python-pillow.org/ · https://numpy.org/ · https://ipywidgets.readthedocs.io/ |

固定的 ComfyUI／外掛版本在 `tools/colab_runtime.py` 的 `PINS`；模型來源在 `MODEL_FILES` 與 `REWRITER`，當次下載版本記錄在執行環境的 `model_download_receipt.json`。

第三方元件及權重依各自來源的授權與條款。Banana MV 的 MIT 授權只適用本倉庫自有程式，不授予第三方模型或使用者素材的額外權利。
