import type { PAGES } from '@/constants';
import type { FC, SVGProps } from 'react';

export type MakeOptional<T, K extends keyof T> = Omit<T, K> & Partial<Pick<T, K>>;

type Enumerate<N extends number, Acc extends number[] = []> = Acc['length'] extends N
  ? Acc[number]
  : Enumerate<N, [...Acc, Acc['length']]>;

export type IntRange<F extends number, T extends number> = Exclude<Enumerate<T>, Enumerate<F>>;

export type Page = (typeof PAGES)[number];

export type PageHeaderConfig = {
  [K in Page]: {
    title: string;
    description: string;
  };
};

export type SvgIcon = FC<SVGProps<SVGSVGElement>>;
