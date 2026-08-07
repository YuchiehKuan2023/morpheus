import type { FC } from 'react';
import type { LlmExplanation } from '@/types';
import { Badge, DialogSection, EvidenceList, RecommendationList } from '@/components';
import { LLM_SECTIONS } from '@/constants/simulation';

interface Props {
  llm: LlmExplanation | null;
}

export const AiAnalysisTab: FC<Props> = ({ llm }) => {
  if (!llm) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
        <p className="text-sm">No LLM explanation available for this anomaly yet.</p>
      </div>
    );
  }

  const evidence = llm.evidenceSummary ?? [];

  return (
    <div className="space-y-4">
      {/* Text sections */}
      {LLM_SECTIONS.map(({ key, label: title }) => {
        const description = llm[key];
        const separator = true;

        if (!description || typeof description !== 'string') return null;

        const actions = (
          <>
            <Badge>Model: {llm.modelUsed}</Badge>
            <Badge variant="lime">complete</Badge>
          </>
        );

        const descriptionNode =
          key === 'recommendations' ? <RecommendationList text={description} /> : description;

        return (
          <DialogSection
            key={key}
            title={title}
            description={descriptionNode}
            actions={actions}
            separator={separator}
          />
        );
      })}

      {/* Evidence Used */}
      {evidence.length > 0 && (
        <DialogSection
          title="Evidence Used"
          description={<EvidenceList items={evidence} />}
          actions={
            <>
              <Badge>
                {evidence.length} item{evidence.length !== 1 ? 's' : ''}
              </Badge>
              <Badge variant="lime">complete</Badge>
            </>
          }
          separator
        />
      )}
    </div>
  );
};
