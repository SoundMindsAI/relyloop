'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDeleteCluster, type ClusterDetail } from '@/lib/api/clusters';

export interface ClusterActionBarProps {
  cluster: ClusterDetail;
}

export function ClusterActionBar({ cluster }: ClusterActionBarProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const del = useDeleteCluster();
  const nameMatches = typed === cluster.name;
  return (
    <div className="flex items-center gap-3">
      <Button
        variant="destructive"
        disabled={del.isPending}
        onClick={() => setOpen(true)}
        data-testid="delete-cluster"
      >
        {del.isPending ? 'Deleting…' : 'Delete cluster'}
      </Button>
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setTyped('');
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{cluster.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              Soft-deletes the cluster from the registry. Studies, query sets, judgment lists, and
              proposals scoped to this cluster remain but lose their parent reference.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <label
              htmlFor="cluster-name-confirm"
              className="text-xs uppercase text-muted-foreground"
            >
              Type the cluster name to confirm
            </label>
            <Input
              id="cluster-name-confirm"
              data-testid="confirm-name-input"
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep cluster</AlertDialogCancel>
            <Button
              variant="destructive"
              data-testid="confirm-delete"
              disabled={!nameMatches || del.isPending}
              onClick={(event) => {
                event.preventDefault();
                del.mutate(cluster.id, {
                  onSuccess: () => {
                    toast.success('Cluster deleted');
                    setOpen(false);
                    setTyped('');
                    router.push('/clusters');
                  },
                });
              }}
            >
              Delete cluster
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
