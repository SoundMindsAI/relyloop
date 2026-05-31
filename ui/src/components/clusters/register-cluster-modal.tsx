// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

import { HelpPopover } from '@/components/common/help-popover';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { EntitySelect } from '@/components/common/entity-select';
import { ENGINE_LABELS } from '@/components/clusters/engine-badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useRegisterCluster } from '@/lib/api/clusters';
import { useConfigRepos } from '@/lib/api/config-repos';
import { ALLOWED_AUTH_PER_ENGINE } from '@/lib/cluster-auth';
import {
  ENGINE_TYPE_VALUES,
  ENVIRONMENT_VALUES,
  type AuthKind,
  type EngineType,
  type Environment,
} from '@/lib/enums';

// Result of POST /api/v1/clusters/test-connection (Story A9 backend).
interface ConnectionTestResult {
  reachable: boolean;
  status: 'green' | 'yellow' | 'red' | 'unreachable';
  version: string | null;
  engine_capabilities: Record<string, unknown> | null;
  error: string | null;
}

type TestStatus =
  | { kind: 'idle' }
  | { kind: 'probing' }
  | { kind: 'result'; result: ConnectionTestResult }
  | { kind: 'error'; code: string; message: string };

interface RegisterClusterFormValues {
  name: string;
  engine_type: EngineType;
  environment: Environment;
  base_url: string;
  auth_kind: AuthKind;
  credentials_ref: string;
  config_repo_id?: string;
  notes?: string;
  target_filter?: string;
}

export interface RegisterClusterModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RegisterClusterModal({ open, onOpenChange }: RegisterClusterModalProps) {
  const register = useRegisterCluster();
  const configRepos = useConfigRepos({ limit: 100 });
  const [submitting, setSubmitting] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>({ kind: 'idle' });
  const form = useForm<RegisterClusterFormValues>({
    defaultValues: {
      name: '',
      engine_type: 'elasticsearch',
      environment: 'dev',
      base_url: '',
      auth_kind: 'es_apikey',
      credentials_ref: '',
      config_repo_id: undefined,
      notes: '',
      target_filter: '',
    },
  });

  // Watch every field that contributes to the connection-test payload and
  // reset the test result whenever any of them change. Without this, an
  // operator who passes the test then edits the URL keeps seeing a stale
  // green "reachable" pip even though the new URL was never probed.
  const watchedEngine = form.watch('engine_type');
  const watchedBaseUrl = form.watch('base_url');
  const watchedAuthKind = form.watch('auth_kind');
  const watchedCredentials = form.watch('credentials_ref');
  useEffect(() => {
    setTestStatus({ kind: 'idle' });
  }, [watchedEngine, watchedBaseUrl, watchedAuthKind, watchedCredentials]);

  // When the engine changes, drop an invalid auth_kind onto the first
  // valid choice for the new engine. The dropdown's filtered options
  // would also visually drop it, but react-hook-form keeps the previous
  // value until we explicitly setValue.
  function onEngineChange(next: EngineType): void {
    form.setValue('engine_type', next);
    const allowed = ALLOWED_AUTH_PER_ENGINE[next];
    const current = form.watch('auth_kind');
    if (!allowed.includes(current)) {
      // tsc --noUncheckedIndexedAccess: allowed[0] is widened to T | undefined
      // but allowed is non-empty by construction (drift-guarded by
      // cluster-auth.test.ts). Narrow explicitly.
      const first = allowed[0];
      if (first) {
        form.setValue('auth_kind', first);
      }
    }
  }

  async function onTestConnection(): Promise<void> {
    setTestStatus({ kind: 'probing' });
    try {
      const res = await fetch('/api/v1/clusters/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          engine_type: form.watch('engine_type'),
          base_url: form.watch('base_url'),
          auth_kind: form.watch('auth_kind'),
          credentials_ref: form.watch('credentials_ref'),
        }),
      });
      if (res.ok) {
        const result = (await res.json()) as ConnectionTestResult;
        setTestStatus({ kind: 'result', result });
        return;
      }
      // Project-standard error envelope: { detail: { error_code, message, retryable } }
      const body = (await res.json().catch(() => ({}))) as {
        detail?: { error_code?: string; message?: string };
      };
      setTestStatus({
        kind: 'error',
        code: body.detail?.error_code ?? `HTTP_${res.status}`,
        message: body.detail?.message ?? `Probe failed (HTTP ${res.status})`,
      });
    } catch (err) {
      setTestStatus({
        kind: 'error',
        code: 'NETWORK',
        message: err instanceof Error ? err.message : 'Network error',
      });
    }
  }

  function submit(values: RegisterClusterFormValues) {
    setSubmitting(true);
    register.mutate(
      {
        name: values.name,
        engine_type: values.engine_type,
        environment: values.environment,
        base_url: values.base_url,
        auth_kind: values.auth_kind,
        credentials_ref: values.credentials_ref,
        engine_config: null,
        notes: values.notes || null,
        target_filter: values.target_filter?.trim() || null,
      },
      {
        onSuccess: (cluster) => {
          toast.success(`Cluster registered — health: ${cluster.health_check.status}`);
          form.reset();
          onOpenChange(false);
        },
        onSettled: () => setSubmitting(false),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Register cluster</DialogTitle>
          <DialogDescription>
            Configure connection + auth. Elasticsearch uses <code>es_apikey</code> or{' '}
            <code>es_basic</code>; OpenSearch uses <code>opensearch_basic</code>; Apache Solr uses{' '}
            <code>solr_basic</code> (<code>BasicAuthPlugin</code>) or <code>solr_apikey</code> (
            <code>JWTAuthPlugin</code>). The Test-connection button probes the cluster before
            registration.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(submit)}
          className="space-y-4"
          data-testid="register-form"
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="cl-name">Name</Label>
              <Input
                id="cl-name"
                {...form.register('name', {
                  required: true,
                  pattern: /^[a-z0-9][a-z0-9-]*$/,
                })}
                placeholder="local-es"
              />
              {form.formState.errors.name && (
                <p className="text-xs text-destructive">
                  Lowercase letters, digits, and dashes only.
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cl-engine">Engine</Label>
              <Select
                value={form.watch('engine_type')}
                onValueChange={(v) => onEngineChange(v as EngineType)}
              >
                <SelectTrigger id="cl-engine">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ENGINE_TYPE_VALUES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {ENGINE_LABELS[v]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-1">
                <Label htmlFor="cl-env">Environment</Label>
                <InfoTooltip glossaryKey="cluster.environment" />
              </div>
              <Select
                value={form.watch('environment')}
                onValueChange={(v) => form.setValue('environment', v as Environment)}
              >
                <SelectTrigger id="cl-env">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ENVIRONMENT_VALUES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-1">
                <Label htmlFor="cl-auth">Auth kind</Label>
                <InfoTooltip glossaryKey="cluster.auth_kind" />
              </div>
              <Select
                value={form.watch('auth_kind')}
                onValueChange={(v) => form.setValue('auth_kind', v as AuthKind)}
              >
                <SelectTrigger id="cl-auth">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* Per-engine filtering: only show auth kinds valid for the */}
                  {/* selected engine — invalid combos can no longer be picked. */}
                  {/* Values must match backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE */}
                  {ALLOWED_AUTH_PER_ENGINE[form.watch('engine_type')].map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cl-url">Base URL</Label>
            <Input
              id="cl-url"
              type="url"
              {...form.register('base_url', { required: true })}
              placeholder="https://es.example.com:9200"
            />
            {form.formState.errors.base_url && (
              <p className="text-xs text-destructive">A base URL is required.</p>
            )}
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1">
              <Label htmlFor="cl-cred">Credentials ref (./secrets/&lt;name&gt;)</Label>
              <HelpPopover glossaryKey="cluster.credentials_ref" />
            </div>
            <Input
              id="cl-cred"
              {...form.register('credentials_ref', { required: true })}
              placeholder="es-apikey"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cl-repo">Config repo (optional)</Label>
            <EntitySelect
              id="cl-repo"
              data-testid="cl-repo"
              query={configRepos}
              getId={(r) => r.id}
              getLabel={(r) => r.name}
              value={form.watch('config_repo_id') || undefined}
              onChange={(v) => form.setValue('config_repo_id', v || undefined)}
              placeholder="—"
              emptyState={{
                message: 'No config repos registered',
                cta: { label: 'Register a config repo', href: '/clusters' },
              }}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cl-notes">Notes</Label>
            <Textarea id="cl-notes" rows={3} {...form.register('notes')} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cl-target-filter">Target filter (optional)</Label>
            <Input
              id="cl-target-filter"
              {...form.register('target_filter')}
              placeholder="products*"
            />
            <p className="text-xs text-muted-foreground">
              Glob pattern restricting which indices appear in the target picker for this cluster.
              Supports <code>*</code> (any chars), <code>?</code> (single char), and{' '}
              <code>[seq]</code> / <code>[!seq]</code> character classes. Example:{' '}
              <code>products*</code> matches every index starting with <em>products</em>. Brace
              expansion (<code>{'{a,b}'}</code>) is NOT supported — register two clusters if you
              need OR-of-globs. Leave blank to show every user-facing index.
            </p>
          </div>
          {/* infra_adapter_solr Story A11: pre-submit "Test connection" button
              + inline result panel. Calls POST /api/v1/clusters/test-connection
              and renders the diagnostic result before the operator commits
              to the registration. Resets to idle on any field change so a
              stale "green" can't survive form edits. */}
          <div
            className="flex flex-col gap-2 sm:flex-row sm:items-center"
            data-testid="test-connection-row"
          >
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                void onTestConnection();
              }}
              disabled={
                testStatus.kind === 'probing' ||
                !form.watch('base_url') ||
                !form.watch('credentials_ref')
              }
              data-testid="test-connection-button"
            >
              {testStatus.kind === 'probing' ? 'Testing…' : 'Test connection'}
            </Button>
            {testStatus.kind === 'result' && testStatus.result.reachable && (
              <span
                className="text-sm text-emerald-600 dark:text-emerald-400"
                data-testid="test-connection-result"
              >
                ✓ {testStatus.result.status}
                {testStatus.result.version ? ` · ${testStatus.result.version}` : ''}
              </span>
            )}
            {testStatus.kind === 'result' && !testStatus.result.reachable && (
              <span
                className="text-sm text-rose-600 dark:text-rose-400"
                data-testid="test-connection-result"
              >
                ✗ {testStatus.result.error ?? 'unreachable'}
              </span>
            )}
            {testStatus.kind === 'error' && (
              <span
                className="text-sm text-rose-600 dark:text-rose-400"
                data-testid="test-connection-result"
              >
                ✗ {testStatus.code}: {testStatus.message}
              </span>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting} data-testid="register-submit">
              {submitting ? 'Registering…' : 'Register'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
