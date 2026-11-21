"""ComfyUI gate for pasting refined faces only when they are distant."""


class BananaFarFaceGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"crops": ("IMAGE",), "transform": ("H3FACEXFORM",)}}

    RETURN_TYPES = ("IMAGE", "H3FACEXFORM")
    FUNCTION = "apply"
    CATEGORY = "Banana/Face Refine"

    def apply(self, crops, transform):
        short_side = min(transform["src_size"])
        canvas_height = transform["canvas"][1]
        weights = []
        for crop, rect, weight in zip(
            transform["boxes"], transform["face_rect"], transform["weights"], strict=True
        ):
            fraction = rect[3] * crop[3] / (canvas_height * short_side)
            # Fade in below 10% of the frame short edge. Larger faces get zero paste.
            distant = max(0.0, min(1.0, (0.10 - fraction) / 0.025))
            weights.append(float(weight) * distant)
        if not any(weights):
            raise ValueError("BANANA_NO_DISTANT_FACE")
        return crops, dict(transform, weights=weights)


NODE_CLASS_MAPPINGS = {"BananaFarFaceGate": BananaFarFaceGate}
NODE_DISPLAY_NAME_MAPPINGS = {"BananaFarFaceGate": "Banana Far Face Gate"}
