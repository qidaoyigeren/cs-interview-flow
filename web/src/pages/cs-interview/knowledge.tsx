import { Button } from '@/components/ui/button';
import {
  useInterviewDatasets,
  useInterviewKnowledgeConfig,
  useInterviewMutations,
} from '@/hooks/use-cs-interview-request';
import { KnowledgeConfigPayload } from '@/interfaces/request/cs-interview';
import dayjs from 'dayjs';
import { AlertTriangle, CheckCircle2, Database, RefreshCw } from 'lucide-react';
import { ChangeEvent, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { InterviewShell, PageHeading } from './components';

const EmptyBindings: KnowledgeConfigPayload = {
  interviewExperienceDatasetId: '',
  leetcodeDatasetId: '',
  fundamentalsDatasetId: '',
  enabled: true,
};

const Bindings = [
  {
    field: 'interviewExperienceDatasetId',
    title: 'csInterview.knowledge.interviewExperience',
    description: 'csInterview.knowledge.interviewExperienceDescription',
  },
  {
    field: 'leetcodeDatasetId',
    title: 'csInterview.knowledge.leetcode',
    description: 'csInterview.knowledge.leetcodeDescription',
  },
  {
    field: 'fundamentalsDatasetId',
    title: 'csInterview.knowledge.fundamentals',
    description: 'csInterview.knowledge.fundamentalsDescription',
  },
] as const;

export default function InterviewKnowledge() {
  const { t } = useTranslation();
  const { data: datasets = [], isLoading } = useInterviewDatasets();
  const { data: savedConfig } = useInterviewKnowledgeConfig();
  const { saveKnowledge, validateKnowledge } = useInterviewMutations();
  const [bindings, setBindings] =
    useState<KnowledgeConfigPayload>(EmptyBindings);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (savedConfig) {
      setBindings({
        id: savedConfig.id,
        interviewExperienceDatasetId: savedConfig.interviewExperienceDatasetId,
        leetcodeDatasetId: savedConfig.leetcodeDatasetId,
        fundamentalsDatasetId: savedConfig.fundamentalsDatasetId,
        enabled: savedConfig.enabled,
      });
    }
  }, [savedConfig]);

  const handleBindingChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setBindings((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }));
  };
  const handleValidate = async () => {
    setMessage(undefined);
    setError(undefined);
    try {
      await validateKnowledge.mutateAsync(bindings);
      setMessage(t('csInterview.knowledge.validationPassed'));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t('csInterview.knowledge.validationFailed'),
      );
    }
  };
  const handleSave = async () => {
    setMessage(undefined);
    setError(undefined);
    try {
      await saveKnowledge.mutateAsync(bindings);
      setMessage(t('csInterview.knowledge.saved'));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t('csInterview.knowledge.saveFailed'),
      );
    }
  };
  const selectedIds = new Set([
    bindings.interviewExperienceDatasetId,
    bindings.leetcodeDatasetId,
    bindings.fundamentalsDatasetId,
  ]);
  const validSelection = selectedIds.size === 3 && !selectedIds.has('');
  const selectClass =
    'mt-4 h-10 w-full rounded-md border border-border-button bg-bg-input px-3 text-sm outline-none focus:ring-1 focus:ring-accent-primary';

  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.knowledge.eyebrow')}
        title={t('csInterview.knowledge.title')}
        description={t('csInterview.knowledge.description')}
      />
      {isLoading ? (
        <div className="h-64 animate-pulse bg-bg-card" />
      ) : datasets.length === 0 ? (
        <div className="border border-state-warning bg-state-warning-5 p-6 text-sm">
          {t('csInterview.knowledge.noDatasets')}
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          {Bindings.map((binding) => {
            const selectedId = bindings[binding.field];
            const dataset = datasets.find((item) => item.id === selectedId);
            const quality =
              savedConfig?.metadataQualitySnapshot?.[binding.field];
            return (
              <section
                key={binding.field}
                className="flex min-h-72 flex-col border border-border-button p-5"
              >
                <div className="flex items-center justify-between">
                  <Database className="size-5 text-text-secondary" />
                  {quality?.metadataQuality?.ready ? (
                    <CheckCircle2 className="size-4 text-state-success" />
                  ) : (
                    <AlertTriangle className="size-4 text-state-warning" />
                  )}
                </div>
                <h2 className="mt-6 font-semibold">{t(binding.title)}</h2>
                <p className="mt-2 text-sm leading-6 text-text-secondary">
                  {t(binding.description)}
                </p>
                <select
                  name={binding.field}
                  value={selectedId}
                  onChange={handleBindingChange}
                  className={selectClass}
                >
                  <option value="">{t('common.selectPlaceholder')}</option>
                  {datasets.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={
                        selectedIds.has(item.id) && item.id !== selectedId
                      }
                    >
                      {item.name}
                    </option>
                  ))}
                </select>
                <div className="mt-auto pt-6 font-mono text-[11px] leading-5 text-text-secondary">
                  {dataset ? (
                    <>
                      <div>
                        {t('csInterview.knowledge.documents', {
                          count: dataset.documentCount,
                        })}
                      </div>
                      <div>
                        {t('csInterview.knowledge.chunks', {
                          count: dataset.chunkCount,
                        })}
                      </div>
                      <div>
                        {t('csInterview.knowledge.updated', {
                          time: dayjs(dataset.updatedAt).format(
                            'YYYY-MM-DD HH:mm',
                          ),
                        })}
                      </div>
                      {quality && (
                        <div>
                          {t('csInterview.knowledge.quality', {
                            value: Math.round(
                              quality.metadataQuality.qualityRatio * 100,
                            ),
                          })}
                        </div>
                      )}
                    </>
                  ) : (
                    t('csInterview.knowledge.notBound')
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
      {(message || error) && (
        <div
          role="status"
          className={`mt-6 border-l-2 px-4 py-3 text-sm ${error ? 'border-state-error bg-state-error-5 text-state-error' : 'border-state-success bg-state-success-5 text-state-success'}`}
        >
          {error || message}
        </div>
      )}
      <div className="mt-8 flex flex-wrap justify-end gap-3 border-t border-border-button pt-6">
        <Button
          variant="outline"
          onClick={handleValidate}
          loading={validateKnowledge.isPending}
          disabled={!validSelection}
        >
          <RefreshCw />
          {t('csInterview.knowledge.validate')}
        </Button>
        <Button
          onClick={handleSave}
          loading={saveKnowledge.isPending}
          disabled={!validSelection}
        >
          {t('common.save')}
        </Button>
      </div>
    </InterviewShell>
  );
}
