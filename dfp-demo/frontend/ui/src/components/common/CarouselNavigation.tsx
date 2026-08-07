import { type FC, useEffect, useState } from 'react';
import type { CarouselApi } from '@/components/ui';
import { ArrowLeft, ArrowRight } from 'lucide-react';

interface Props {
  carouselApi: CarouselApi;
}

const CarouselNavigation: FC<Props> = ({ carouselApi }) => {
  const [canPrev, setCanPrev] = useState(false);
  const [canNext, setCanNext] = useState(false);

  useEffect(() => {
    if (!carouselApi) return;

    const update = () => {
      setCanPrev(carouselApi.canScrollPrev());
      setCanNext(carouselApi.canScrollNext());
    };

    update();
    carouselApi.on('select', update);
    carouselApi.on('reInit', update);

    return () => {
      carouselApi.off('select', update);
      carouselApi.off('reInit', update);
    };
  }, [carouselApi]);

  return (
    <div className="flex gap-2">
      <button
        className="carousel-control"
        aria-label="Previous users"
        onClick={() => carouselApi?.scrollPrev()}
        disabled={!canPrev}
      >
        <ArrowLeft className="h-4 w-4" />
      </button>
      <button
        className="carousel-control"
        aria-label="Next users"
        onClick={() => carouselApi?.scrollNext()}
        disabled={!canNext}
      >
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
};

export default CarouselNavigation;
