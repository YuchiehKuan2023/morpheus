import type { FC } from 'react';

interface Props {
  confidence?: number; // 0-100
}

const Confidence: FC<Props> = ({ confidence }) => {
  if (confidence == null || typeof confidence !== 'number') return null;

  const clampedConfidence = Math.min(100, Math.max(0, confidence));

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-1 w-[50%]">
      <span className="text-gray-400 font-medium shrink-0 w-18">Confidence</span>
      <div className="flex-1 bg-gray-200 rounded-full h-3 overflow-hidden">
        <div
          className="h-full bg-dark-lime rounded-full transition-all duration-700"
          style={{ width: `${clampedConfidence}%` }}
        />
      </div>
      <span className="text-dark-lime font-semibold tabular-nums w-9 text-right">
        {clampedConfidence}%
      </span>
    </div>
  );
};

export default Confidence;
