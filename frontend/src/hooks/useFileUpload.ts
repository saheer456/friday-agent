import { useState, useCallback } from 'react';
import { authFetch } from '../lib/api';

export function useFileUpload() {
  const [isUploading, setIsUploading] = useState(false);
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'error' | '' } | null>(null);

  const showToast = useCallback((text: string, type: 'success' | 'error' | '' = '') => {
    setToastMessage({ text, type });
    if (type === 'success' || type === 'error') {
      setTimeout(() => setToastMessage(null), 3500);
    }
  }, []);

  const uploadFile = useCallback(async (file: File) => {
    const MAX_MB = 20;
    if (file.size > MAX_MB * 1024 * 1024) {
      showToast(`File too large. Max ${MAX_MB} MB.`, 'error');
      return null;
    }

    const ALLOWED = ['.pdf', '.docx', '.txt', '.md', '.csv', '.json'];
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED.includes(ext)) {
      showToast(`Unsupported type. Allowed: ${ALLOWED.join(', ')}`, 'error');
      return null;
    }

    setIsUploading(true);
    showToast(`Ingesting "${file.name}"…`);

    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await authFetch('/api/upload', { method: 'POST', body: fd });
      const data = await res.json();

      if (!res.ok) {
        showToast(data.detail || 'Upload failed.', 'error');
        return null;
      }

      showToast(`✓ "${data.filename}" ingested — ${data.chunks} chunks, ~${data.words} words`, 'success');
      return data;
    } catch (err) {
      showToast('Network error during upload.', 'error');
      return null;
    } finally {
      setIsUploading(false);
    }
  }, [showToast]);

  return { isUploading, toastMessage, uploadFile };
}
