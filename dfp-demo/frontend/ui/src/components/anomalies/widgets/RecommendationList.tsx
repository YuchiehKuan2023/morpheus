import type { FC } from 'react';

interface Props {
  text: string;
}

export const RecommendationList: FC<Props> = (props) => {
  const { text } = props;

  const items = text
    .split('\n')
    .map((line) => line.match(/^\d+\.\s+(.+)/)?.[1] ?? line.trim())
    .filter(Boolean);

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-2">
          <span className="numbered-item mt-0.5 shrink-0">{i + 1}</span>
          <span className="text-sm text-muted-foreground leading-relaxed">{item}</span>
        </div>
      ))}
    </div>
  );
};
