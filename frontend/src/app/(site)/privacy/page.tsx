import type { Metadata } from 'next';
import { InfoPage } from '@/components/InfoPage';

export const metadata: Metadata = {
  title: 'Privacy Policy - LingoDoc',
  description: 'How LingoDoc handles account, upload, payment, and product usage information.',
};

export default function PrivacyPage() {
  return (
    <InfoPage
      eyebrow="Privacy"
      title="Privacy Policy"
      description="This policy explains what information LingoDoc collects, how it is used, and the choices available when you use the PDF translation service."
      updated="June 16, 2026"
      sections={[
        {
          title: 'Information we collect',
          children: (
            <>
              <p>
                We collect account information provided through Clerk, such as your user identifier and email address when available. We also store metadata about uploaded files, including filename, file size, page count, upload time, translation task status, language choices, plan, and usage counts.
              </p>
              <p>
                When you upload a PDF, LingoDoc stores the file and generated translation outputs so the app can provide previews, downloads, and file history. Payment and subscription events are processed through Paddle and stored only as needed to maintain your plan status.
              </p>
            </>
          ),
        },
        {
          title: 'How we use information',
          children: (
            <>
              <p>
                We use your information to authenticate access, process PDF uploads, run translations, render previews, prepare downloadable PDFs, show file history, enforce plan limits, calculate monthly usage, process subscriptions, and troubleshoot service issues.
              </p>
              <p>
                Uploaded PDFs and extracted text may be sent to translation infrastructure configured for the service so that translated output can be generated. We do not use your documents to create public examples or marketing material without permission.
              </p>
            </>
          ),
        },
        {
          title: 'Storage and retention',
          children: (
            <>
              <p>
                Files, page-level translation results, cached exports, and task records are retained to support previews, downloads, and your dashboard history. You can delete files from your dashboard, which removes the file record and associated stored outputs from the application storage path.
              </p>
              <p>
                Some operational records, such as payment events, security logs, or backups, may remain for a limited period where needed for accounting, abuse prevention, debugging, or legal compliance.
              </p>
            </>
          ),
        },
        {
          title: 'Sharing',
          children: (
            <>
              <p>
                We share information with service providers that operate core parts of LingoDoc, including authentication, payment processing, storage, hosting, and translation services. These providers process information on our behalf or under their own terms where applicable.
              </p>
              <p>
                We may disclose information if required by law, to protect the service from abuse, or to investigate security and reliability incidents.
              </p>
            </>
          ),
        },
        {
          title: 'Security',
          children: (
            <>
              <p>
                LingoDoc uses authenticated API access for private files and signed URLs for short-lived preview or download access. We also restrict file access by ownership in the backend.
              </p>
              <p>
                No online service can guarantee absolute security. Use caution when uploading highly sensitive, regulated, confidential, or legally privileged documents.
              </p>
            </>
          ),
        },
        {
          title: 'Your choices',
          children: (
            <>
              <p>
                You can choose not to upload a document, delete uploaded files from your dashboard, or stop using the service. Subscription management and billing actions are handled through Paddle checkout and related subscription flows.
              </p>
              <p>
                For privacy questions or account-related requests, contact us at <a className="font-semibold text-emerald-600" href="mailto:support@lingodoc.xyz">support@lingodoc.xyz</a>.
              </p>
            </>
          ),
        },
      ]}
    />
  );
}
