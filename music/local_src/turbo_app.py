import spaces
import gradio as gr
import torch
import numpy as np
import tempfile
import soundfile as sf
from diffusers import AceStepPipeline

# ─── Model Loading (CPU at module level for ZeroGPU) ─────────────────────
MODEL_ID = "ACE-Step/acestep-v15-xl-turbo-diffusers"
pipe = AceStepPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
pipe.vae.enable_tiling()

# ─── Inference ───────────────────────────────────────────────────────────

@spaces.GPU(duration=180)
def generate_music(prompt, lyrics, duration, seed, num_steps):
    """Generate music from text prompt and optional lyrics."""
    if not prompt.strip():
        raise gr.Error("Please enter a music prompt!")

    # Move to GPU inside @spaces.GPU where CUDA is available
    pipe.to("cuda")

    generator = torch.Generator(device="cuda").manual_seed(int(seed))

    output = pipe(
        prompt=prompt,
        lyrics=lyrics if lyrics.strip() else None,
        audio_duration=float(duration),
        num_inference_steps=int(num_steps),
        generator=generator,
    )

    audio = output.audios[0]  # (channels, samples) @ 48kHz

    # Convert to numpy and save as wav
    if isinstance(audio, torch.Tensor):
        audio = audio.cpu().numpy()

    # If stereo (2, samples), transpose for soundfile
    if audio.ndim == 2:
        audio = audio.T  # (samples, channels)

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio, samplerate=48000)

    return tmp.name

# ─── UI ──────────────────────────────────────────────────────────────────

DESCRIPTION = """
# 🎵 ACE-Step Turbo — AI Music Generator

Generate music from text descriptions and optional lyrics using **ACE-Step v1.5 XL Turbo** — 
a 5B-parameter flow-matching DiT model distilled for fast 8-step generation.

### What's New
This uses the **brand-new diffusers-formatted Turbo model** (released April 22, 2026) — 
guidance-distilled for speed without sacrificing quality. MIT licensed.
"""

EXAMPLES = [
    ["An upbeat synthwave track with driving drums and a catchy lead synth melody", "[Verse]\nNeon lights are calling me\nRunning through the city free\n[Chorus]\nRide the wave tonight\nEverything feels right", 30, 42, 8],
    ["A peaceful acoustic guitar piece with gentle fingerpicking, nature ambience", "", 20, 123, 8],
    ["Heavy metal with distorted guitars, double bass drums, and aggressive vocals", "[Verse]\nFire in the sky\nWe will never die\n[Chorus]\nRise up, stand tall\nWe won't ever fall", 30, 456, 8],
    ["Lo-fi hip hop beats to relax/study to, warm vinyl crackle, mellow piano", "", 30, 789, 8],
    ["Epic orchestral film score with soaring strings, brass fanfare, and timpani", "", 30, 321, 8],
    ["Jazz trio — upright bass, piano, and brushed drums, smoky nightclub vibe", "", 25, 654, 8],
]

with gr.Blocks(
    title="ACE-Step Turbo — AI Music Generator",
    theme=gr.themes.Soft(primary_hue="orange", secondary_hue="amber"),
    css="footer { display: none !important; }"
) as demo:
    gr.Markdown(DESCRIPTION)

    with gr.Row():
        with gr.Column(scale=2):
            prompt = gr.Textbox(
                label="🎶 Music Description",
                placeholder="Describe the music style, instruments, mood, tempo...",
                lines=3,
            )
            lyrics = gr.Textbox(
                label="📝 Lyrics (Optional)",
                placeholder="[Verse]\nYour lyrics here...\n[Chorus]\nChorus lyrics...",
                lines=5,
            )
        with gr.Column(scale=1):
            duration = gr.Slider(5, 60, value=30, step=5, label="⏱️ Duration (seconds)")
            num_steps = gr.Slider(4, 16, value=8, step=1, label="🔄 Inference Steps")
            seed = gr.Number(value=42, label="🎲 Seed", precision=0)
            btn = gr.Button("🎵 Generate Music", variant="primary", size="lg")

    audio_output = gr.Audio(label="Generated Music", type="filepath")

    btn.click(
        fn=generate_music,
        inputs=[prompt, lyrics, duration, seed, num_steps],
        outputs=audio_output,
    )

    gr.Examples(
        examples=EXAMPLES,
        inputs=[prompt, lyrics, duration, seed, num_steps],
        outputs=audio_output,
        fn=generate_music,
        cache_examples=False,
    )

    gr.Markdown("""
---
**Model:** [ACE-Step v1.5 XL Turbo](https://huggingface.co/ACE-Step/acestep-v15-xl-turbo-diffusers) | **Architecture:** 5B DiT, flow-matching, guidance-distilled | **License:** MIT | **Audio:** 48kHz stereo
""")

demo.launch()
