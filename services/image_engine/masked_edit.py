"""Binary-mask output compositing. This does not perform model inpainting."""
import hashlib
import io
from PIL import Image


def load_pair(reference_path, mask_path):
    with Image.open(reference_path) as source:
        reference = source.convert('RGBA')
    with Image.open(mask_path) as source:
        if source.format != 'PNG' or source.getexif().get(274, 1) != 1:
            raise ValueError('Mask must be an upright PNG')
        rgba = source.convert('RGBA')
    if rgba.size != reference.size:
        raise ValueError('Mask dimensions must exactly match the upright reference image')
    r, g, b, a = rgba.split()
    if r.tobytes() != g.tobytes() or r.tobytes() != b.tobytes() or a.getextrema() != (255, 255):
        raise ValueError('Mask must be opaque black and white; transparency and colour are unsupported')
    values = set(r.tobytes())  # single-band 8-bit: bytes are the pixel values
    if values != {0, 255}:
        raise ValueError('Mask must contain both black protected pixels and white editable pixels, with no grey')
    return reference, r


def composite_edit(reference_path, mask_path, generated_bytes):
    reference, mask = load_pair(reference_path, mask_path)
    with Image.open(io.BytesIO(generated_bytes)) as source:
        candidate = source.convert('RGBA')
    ratio = (candidate.width / candidate.height) / (reference.width / reference.height)
    if abs(ratio - 1) > 0.02:
        raise ValueError('Generated image framing differs from the reference; masked output withheld')
    original_size = candidate.size
    if candidate.size != reference.size:
        candidate = candidate.resize(reference.size, Image.Resampling.LANCZOS)
    result = Image.composite(candidate, reference, mask)
    buffer = io.BytesIO()
    result.save(buffer, format='PNG')
    with open(reference_path, 'rb') as stream:
        reference_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    with open(mask_path, 'rb') as stream:
        mask_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    return buffer.getvalue(), {
        'edit_method': 'binary_mask_output_composite',
        'reference_sha256': reference_hash, 'mask_sha256': mask_hash,
        'generated_size': list(original_size), 'output_size': list(reference.size),
        'candidate_resized': original_size != reference.size,
        'outside_mask': 'original decoded RGBA pixels',
        'geometry_inside_mask_verified': False,
    }
