import { useEffect } from 'react';
import { useLightboxStore } from '../state/lightboxStore';
import './lightbox.css';

export function Lightbox() {
  const url = useLightboxStore((s) => s.url);
  const close = useLightboxStore((s) => s.close);

  useEffect(() => {
    if (!url) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === 'Escape' && close();
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [url, close]);

  if (!url) return null;

  return (
    <div className="lightbox-backdrop" onClick={close}>
      <img className="lightbox-image" src={url} alt="" onClick={(e) => e.stopPropagation()} />
      <button className="lightbox-close" onClick={close} title="Close (Esc)">
        ✕
      </button>
    </div>
  );
}
