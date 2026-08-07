import { type FC } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui';
import type { UserDetailProps } from '@/types';
import { PillTabs, UserDetails, LoadingDialog, ErrorDialog, Metrics } from '@/components';
import { DIALOG_TABS } from '@/constants/users';
import { mapToUserDetail } from '@/utils/users';
import { DetailsTab, AnomaliesTab, BaselineTab, DetectionsTab } from './tabs';
import { useUserDetails } from '@/hooks';

const UserDialog: FC<UserDetailProps> = (props) => {
  const userDetails = useUserDetails(props);

  if (!userDetails) return null;

  const { user, title, loading, detail, error, activeTab, setActiveTab, onClose, open } =
    userDetails;

  if (!user) return null;

  if (loading) return <LoadingDialog {...{ open, onClose, title }} />;

  if (detail === null) return <ErrorDialog {...{ open, onClose, title, error }} />;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[95vh] overflow-hidden flex flex-col">
        <DialogHeader className="shrink-0">
          <div className="space-y-1">
            <DialogTitle className="text-2xl">{title}</DialogTitle>
            <DialogDescription className="sr-only">User Details Dialog</DialogDescription>
            <div className="pt-2">
              <div className="text-xs mb-2 avatar-md">
                <UserDetails user={mapToUserDetail(user)} />
              </div>
              <div className="user-metrics">
                <div className="grid grid-cols-4 gap-3 mt-6">
                  <Metrics {...{ detail }} />
                </div>
              </div>
            </div>
          </div>
        </DialogHeader>

        <PillTabs
          tabs={DIALOG_TABS}
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex-1 min-h-0"
          navClassName="mt-4"
        >
          <DetailsTab {...{ detail, loading }} type="details" />
          <AnomaliesTab username={user.username} type="anomalies" loading={loading} />
          <BaselineTab {...{ detail, loading }} type="baseline" />
          <DetectionsTab {...{ detail, loading }} type="detections" />
        </PillTabs>
      </DialogContent>
    </Dialog>
  );
};

export default UserDialog;
