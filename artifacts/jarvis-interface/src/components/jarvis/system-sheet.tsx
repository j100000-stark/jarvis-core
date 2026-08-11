/**
 * SystemSheet — slide-up system status overlay.
 * Reuses the existing SystemPanel component unchanged.
 */
import { X } from 'lucide-react';
import { SystemPanel } from './system-panel';

interface SystemSheetProps {
  open: boolean;
  onClose: () => void;
}

export function SystemSheet({ open, onClose }: SystemSheetProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col" style={{ background: 'rgba(0,0,0,0.88)' }}>
      <div className="flex-1 cursor-pointer" onClick={onClose} />

      <div
        className="flex flex-col rounded-t-3xl border-t overflow-hidden"
        style={{
          background: 'rgba(3,8,18,0.97)',
          borderColor: 'rgba(0,160,255,0.18)',
          maxHeight: '88dvh',
          backdropFilter: 'blur(24px)',
        }}
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b shrink-0"
          style={{ borderColor: 'rgba(0,160,255,0.10)' }}
        >
          <span
            className="font-mono text-[10px] uppercase tracking-[0.22em]"
            style={{ color: 'rgba(0,180,255,0.5)' }}
          >
            System status
          </span>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-xl transition"
            style={{ color: 'rgba(0,180,255,0.5)' }}
            aria-label="Close system panel"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <SystemPanel />
        </div>
      </div>
    </div>
  );
}
