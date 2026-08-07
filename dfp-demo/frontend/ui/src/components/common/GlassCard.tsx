import type { FC, ReactNode } from 'react';
import { cn } from '@/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui';

interface GlassCardProps {
  className?: string;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  separator?: boolean;
}

const GlassCard: FC<GlassCardProps> = ({
  className,
  title,
  description,
  children,
  actions,
  separator,
}) => {
  const classNames = cn(className, 'card hover:shadow-md transition-shadow glass-card');

  return (
    <Card className={classNames}>
      <CardHeader className="card-header p-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="card-title">{title}</CardTitle>
          </div>
          {actions}
        </div>
        {separator && <div className="separator mt-2 mb-4 -ml-3 -mr-3" />}
        {description && <div className="text-sm text-muted-foreground mt-1">{description}</div>}
      </CardHeader>
      <CardContent className="card-content">{children}</CardContent>
    </Card>
  );
};

export default GlassCard;
