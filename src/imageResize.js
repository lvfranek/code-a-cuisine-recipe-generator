// Shrinks a photo in the browser before upload: longest side <= maxSide, JPEG.
// A 4-12 MB phone photo becomes ~0.2-0.4 MB, which uploads fast on mobile data
// and is plenty for recognising food. EXIF orientation is applied, so the
// picture is never sideways; other EXIF data (e.g. GPS) is dropped by the canvas.

async function decode(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      // fall through to <img> decoding (older Safari)
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function resizeImage(file, maxSide = 1280, quality = 0.8) {
  let source;
  try {
    source = await decode(file);
  } catch {
    throw new Error("This image can't be read. Please use a JPEG or PNG photo.");
  }
  const width = source.width || source.naturalWidth;
  const height = source.height || source.naturalHeight;
  const scale = Math.min(1, maxSide / Math.max(width, height));

  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  source.close?.();

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
  if (!blob) throw new Error("This image can't be read. Please use a JPEG or PNG photo.");
  return blob;
}
