import type { Metadata } from "next";
import { CONTACTO_EMAIL, LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Privacy Policy · instagod" };

export default function PrivacyPage() {
  return (
    <LegalPage
      titulo="Privacy Policy"
      secciones={[
        {
          titulo: "1. Overview",
          contenido: (
            <p>
              This policy explains what information instagod collects, how it is used and how you
              can have it deleted. instagod is an invitation-only tool for managing and publishing
              content to brand social media accounts.
            </p>
          ),
        },
        {
          titulo: "2. Information we collect",
          contenido: (
            <ul className="list-disc space-y-2 pl-5">
              <li>
                <strong>Team accounts:</strong> name, email address and a hashed password, plus a
                session cookie to keep you signed in.
              </li>
              <li>
                <strong>Connected TikTok accounts:</strong> when you connect TikTok via Login Kit,
                we receive your TikTok open ID, display name and avatar, and the access and refresh
                tokens TikTok issues for the permissions you grant.
              </li>
              <li>
                <strong>Content:</strong> the images, videos, captions and schedules created in
                instagod for publishing.
              </li>
            </ul>
          ),
        },
        {
          titulo: "3. How we use it",
          contenido: (
            <ul className="list-disc space-y-2 pl-5">
              <li>To sign you in and run the service.</li>
              <li>
                To publish content that has been reviewed and approved in instagod to the TikTok
                account you connected, using the TikTok Content Posting API.
              </li>
              <li>To show you the status of published content.</li>
            </ul>
          ),
        },
        {
          titulo: "4. What we do not do",
          contenido: (
            <p>
              We do not sell your data, use it for advertising, or share it with third parties
              except the providers that host the service (cloud hosting and media storage), and
              only as needed to run it. We do not post anything to your account without approval
              in instagod.
            </p>
          ),
        },
        {
          titulo: "5. Storage and security",
          contenido: (
            <p>
              Access and refresh tokens are stored encrypted on our servers and are never shown in
              the interface. Access to instagod is limited to invited team members.
            </p>
          ),
        },
        {
          titulo: "6. Retention and deletion",
          contenido: (
            <p>
              We keep your data while your account or connection is active. When you disconnect
              TikTok, we delete its tokens. You can also revoke access at any time from your
              TikTok app settings. To request deletion of all your data, email us; we will
              complete it within 30 days.
            </p>
          ),
        },
        {
          titulo: "7. Changes",
          contenido: (
            <p>
              We may update this policy. The date at the top of this page shows the latest
              version.
            </p>
          ),
        },
        {
          titulo: "8. Contact",
          contenido: (
            <p>
              Privacy questions or deletion requests:{" "}
              <a href={`mailto:${CONTACTO_EMAIL}`} className="underline">
                {CONTACTO_EMAIL}
              </a>
            </p>
          ),
        },
      ]}
    />
  );
}
