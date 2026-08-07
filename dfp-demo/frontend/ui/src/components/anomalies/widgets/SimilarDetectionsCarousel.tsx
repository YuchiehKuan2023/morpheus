import { CarouselNavigation, GlassCard } from '@/components';
import { Carousel, CarouselContent, CarouselItem, type CarouselApi } from '@/components/ui';
import { getItemTitle, objectEntries, toTitleCase, formatScalar } from '@/utils';
import { useState, type FC } from 'react';

interface Props {
  items: Record<string, unknown>[];
}

/** Renders similar_detections as a 3-up carousel. */
export const SimilarDetectionsCarousel: FC<Props> = (props) => {
  const { items } = props;

  const [api, setApi] = useState<CarouselApi>();

  const EXCLUDED_KEYS = ['anomaly_id', 'user_id'];

  return (
    <div className="space-y-2">
      <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
      <div className="flex items-center justify-between">
        <div className="result-row">
          <span className="result-row--title">Similar Detections</span>
          <span className="text-xs text-muted-foreground ml-2">({items.length})</span>
        </div>
        {items.length > 3 && <CarouselNavigation carouselApi={api} />}
      </div>
      <Carousel opts={{ align: 'start', slidesToScroll: 3 }} className="w-full" setApi={setApi}>
        <CarouselContent className="-ml-2">
          {items.map((item, i) => {
            const title = getItemTitle(item);
            const entries = objectEntries(item, true).filter(([k]) => !EXCLUDED_KEYS.includes(k));

            return (
              <CarouselItem key={i} className="basis-1/3 pl-2">
                <GlassCard
                  title={
                    <div className="flex items-center gap-2 mb-2">
                      <span className="numbered-item">{i + 1}</span>
                      {title && <span className="text-xs font-bold truncate">{title}</span>}
                    </div>
                  }
                  description={entries.map(([k, v]) => {
                    const key = k === 'ts' ? 'date' : k.replace(/_/g, ' ');
                    return (
                      <div key={k} className="text-xs pl-1">
                        <strong>{toTitleCase(key)}</strong>: {formatScalar(k, v)}
                      </div>
                    );
                  })}
                  className="no-border no-shadow glass-card--xs"
                />
              </CarouselItem>
            );
          })}
        </CarouselContent>
      </Carousel>
      <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
    </div>
  );
};
