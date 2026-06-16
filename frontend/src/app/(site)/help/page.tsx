import type { Metadata } from 'next';
import Link from 'next/link';
import { InfoPage } from '@/components/InfoPage';

export const metadata: Metadata = {
  title: 'Help - LingoDoc',
  description: 'Help and support for uploading, translating, previewing, and exporting PDFs in LingoDoc.',
};

export default function HelpPage() {
  return (
    <InfoPage
      eyebrow="Help"
      title="Help Center"
      description="Find quick answers about uploading PDFs, plan limits, translation progress, previews, downloads, and account history."
      updated="June 16, 2026"
      sections={[
        {
          title: 'Uploading PDFs',
          children: (
            <>
              <p>
                Sign in, open the home page, and drop a PDF into the upload area or choose one from your file browser. LingoDoc accepts PDF files and checks the file against your current plan&apos;s size limit.
              </p>
              <p>
                If an upload is rejected, confirm the file is a valid PDF and that it fits your plan&apos;s file-size limit. You can review plan limits on the <Link className="font-semibold text-emerald-600" href="/pricing">pricing page</Link>.
              </p>
            </>
          ),
        },
        {
          title: 'Starting translation',
          children: (
            <>
              <p>
                After upload, choose source and target languages in the translation workspace and select Translate. The app checks your remaining monthly pages and per-file page limit before starting.
              </p>
              <p>
                Free accounts translate only the configured preview pages for each PDF. Paid accounts can translate full documents within their plan limits.
              </p>
            </>
          ),
        },
        {
          title: 'Progress and previews',
          children: (
            <>
              <p>
                Translation runs page by page. The progress bar shows completed work, and the page preview becomes available after results are ready. You can change pages and zoom in the preview toolbar.
              </p>
              <p>
                If a previously started task is still recoverable, opening it again from your file history can resume progress rather than starting from scratch.
              </p>
            </>
          ),
        },
        {
          title: 'Downloading PDFs',
          children: (
            <>
              <p>
                When translation is complete, select Download and choose either a bilingual PDF or a translation-only PDF. LingoDoc prepares exports as separate jobs, so larger files may take a little time before the browser download starts.
              </p>
              <p>
                If your translation is partial, the export contains only the translated preview pages and the app shows a notice before download.
              </p>
            </>
          ),
        },
        {
          title: 'File history',
          children: (
            <>
              <p>
                Open <Link className="font-semibold text-emerald-600" href="/dashboard">My Files</Link> to view uploaded PDFs, translation status, file size, page count, and recent tasks. Completed files can be reopened from history.
              </p>
              <p>
                You can delete a file from the dashboard. Deleting removes the file record and related generated outputs from the app&apos;s storage path.
              </p>
            </>
          ),
        },
        {
          title: 'Getting support',
          children: (
            <>
              <p>
                For account, billing, upload, translation, or download issues, contact <a className="font-semibold text-emerald-600" href="mailto:support@lingodoc.xyz">support@lingodoc.xyz</a>.
              </p>
              <p>
                Include the email on your account, the filename, approximate upload time, and what you were trying to do. Do not send private documents by email unless support specifically asks for a safe transfer method.
              </p>
            </>
          ),
        },
      ]}
    />
  );
}
