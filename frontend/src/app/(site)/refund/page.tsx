import type { Metadata } from 'next';
import { InfoPage } from '@/components/InfoPage';

export const metadata: Metadata = {
  title: 'Refund Policy - LingoDoc',
  description: 'Refund and cancellation policy for LingoDoc subscriptions and digital PDF translation services.',
};

export default function RefundPage() {
  return (
    <InfoPage
      eyebrow="Refunds"
      title="Refund Policy"
      description="This policy explains how cancellations and refund requests are handled for LingoDoc subscriptions and digital PDF translation services."
      updated="June 19, 2026"
      sections={[
        {
          title: 'Overview',
          children: (
            <>
              <p>
                LingoDoc provides a digital PDF translation service. Because translated pages, previews, and exported files are generated on demand, payments are generally non-refundable once the service has been substantially used.
              </p>
              <p>
                We review refund requests fairly and in line with this policy, the nature of the service provided, and any consumer rights that apply in your location.
              </p>
            </>
          ),
        },
        {
          title: 'Cancellations',
          children: (
            <>
              <p>
                You may cancel your subscription at any time. Cancellation stops future renewals, but it does not automatically refund charges that have already been paid.
              </p>
              <p>
                Unless otherwise required by law or stated during checkout, your paid access will usually continue until the end of the current billing period after cancellation.
              </p>
            </>
          ),
        },
        {
          title: 'Refund eligibility',
          children: (
            <>
              <p>
                First-time subscribers may request a refund within 14 days of the initial purchase if the paid service has not been substantially used.
              </p>
              <p>
                Substantial use may include translating multiple documents, consuming a meaningful portion of your page allowance, exporting translated files, downloading completed outputs, or otherwise receiving the main benefit of the paid service.
              </p>
            </>
          ),
        },
        {
          title: 'Non-refundable items',
          children: (
            <>
              <p>
                Completed translation jobs, exported PDFs, downloaded outputs, consumed page allowances, partially used billing periods, and subscription renewals are generally non-refundable.
              </p>
              <p>
                We may decline refund requests that involve abuse of the service, repeated refund requests, violation of our terms, or attempts to use paid translation features without payment.
              </p>
            </>
          ),
        },
        {
          title: 'Service issues',
          children: (
            <>
              <p>
                If a material technical issue prevents you from using a paid LingoDoc feature and we cannot reasonably resolve it, you may be eligible for a full or partial refund.
              </p>
              <p>
                Translation quality and PDF layout can vary depending on the source document. Minor formatting differences, terminology choices, or translation results that require review do not automatically qualify for a refund.
              </p>
            </>
          ),
        },
        {
          title: 'How to request a refund',
          children: (
            <>
              <p>
                To request a refund, contact <a className="font-semibold text-emerald-600" href="mailto:support@lingodoc.xyz">support@lingodoc.xyz</a> with the email address used for your account, your Paddle order or transaction details if available, and a brief explanation of the request.
              </p>
              <p>
                Approved refunds are processed through Paddle and returned to the original payment method. Bank, card network, and payment provider processing times may vary.
              </p>
            </>
          ),
        },
        {
          title: 'Consumer rights',
          children: (
            <p>
              Nothing in this policy limits any mandatory consumer rights you may have under applicable law. Where local law gives you additional refund or cancellation rights, those rights continue to apply.
            </p>
          ),
        },
      ]}
    />
  );
}
