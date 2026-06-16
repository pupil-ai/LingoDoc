import type { Metadata } from 'next';
import { InfoPage } from '@/components/InfoPage';

export const metadata: Metadata = {
  title: 'Terms of Service - LingoDoc',
  description: 'Terms for using LingoDoc PDF translation, preview, and export features.',
};

export default function TermsPage() {
  return (
    <InfoPage
      eyebrow="Terms"
      title="Terms of Service"
      description="These terms describe the rules for using LingoDoc, including uploads, translations, subscriptions, exports, and account access."
      updated="June 16, 2026"
      sections={[
        {
          title: 'Using LingoDoc',
          children: (
            <>
              <p>
                LingoDoc provides PDF upload, translation, preview, and export tools for review and reading workflows. You are responsible for the documents you upload and for making sure you have the right to process and translate them.
              </p>
              <p>
                You must not use LingoDoc to upload malware, attack the service, violate another party&apos;s rights, or process content in a way that is unlawful in your jurisdiction.
              </p>
            </>
          ),
        },
        {
          title: 'Accounts and access',
          children: (
            <>
              <p>
                Some features require a signed-in account. You are responsible for maintaining access to your authentication provider account and for activity that occurs through your account.
              </p>
              <p>
                We may restrict or suspend access when needed to protect the service, enforce these terms, comply with law, or prevent abuse.
              </p>
            </>
          ),
        },
        {
          title: 'Plans and limits',
          children: (
            <>
              <p>
                LingoDoc uses plan-based limits for monthly translated pages, pages per PDF, and file size. Free accounts may receive partial preview translations instead of full-document translations.
              </p>
              <p>
                Paid plans, pricing, taxes, renewal terms, cancellation, and payment methods are handled through Paddle checkout and related subscription services. Plan features may change over time, but active users will continue to receive the functionality made available for their current plan during the relevant billing period.
              </p>
            </>
          ),
        },
        {
          title: 'Translation output',
          children: (
            <>
              <p>
                Translations are generated automatically and may contain mistakes, formatting issues, omissions, or terminology choices that require human review. LingoDoc is designed to preserve layout where possible, but PDF structure varies widely and exact fidelity is not guaranteed.
              </p>
              <p>
                You should review translated documents before relying on them for legal, medical, financial, academic, immigration, contractual, or other high-stakes purposes.
              </p>
            </>
          ),
        },
        {
          title: 'User content',
          children: (
            <>
              <p>
                You retain your rights in the PDFs and content you upload. You grant LingoDoc the limited permission needed to store, analyze, translate, render, preview, and export your documents as part of providing the service.
              </p>
              <p>
                Do not upload content that you are not allowed to process through third-party infrastructure or automated translation systems.
              </p>
            </>
          ),
        },
        {
          title: 'Availability',
          children: (
            <>
              <p>
                We aim to keep LingoDoc reliable, but the service may be unavailable during maintenance, provider outages, rate limits, deployment issues, or unexpected incidents. Large PDFs may take longer to process and may fail if they exceed plan limits or operational constraints.
              </p>
              <p>
                To the extent allowed by law, LingoDoc is provided without warranties of uninterrupted availability, perfect accuracy, or exact PDF layout reproduction.
              </p>
            </>
          ),
        },
        {
          title: 'Contact',
          children: (
            <p>
              Questions about these terms can be sent to <a className="font-semibold text-emerald-600" href="mailto:support@lingodoc.com">support@lingodoc.com</a>.
            </p>
          ),
        },
      ]}
    />
  );
}
