import type { Metadata } from "next";
import { CONTACTO_EMAIL, LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Terms of Service · instagod" };

export default function TermsPage() {
  return (
    <LegalPage
      titulo="Terms of Service"
      secciones={[
        {
          titulo: "1. About instagod",
          contenido: (
            <p>
              instagod is a content management tool used by an invited team to create, review,
              schedule and publish content for the social media accounts of the brands it manages.
              Access is by invitation only. By using instagod you agree to these terms.
            </p>
          ),
        },
        {
          titulo: "2. Accounts",
          contenido: (
            <p>
              You are responsible for keeping your credentials secure and for all activity under
              your account. We may suspend or remove access at any time, for example if these terms
              are breached.
            </p>
          ),
        },
        {
          titulo: "3. Connected social media accounts",
          contenido: (
            <>
              <p>
                You may connect social media accounts (such as TikTok or Instagram) that you own or
                are authorized to manage. By connecting an account you authorize instagod to publish
                content to it on your behalf, only after that content has been reviewed and
                approved in instagod.
              </p>
              <p>
                Your use of each platform remains subject to that platform&apos;s own terms,
                including the TikTok Terms of Service and Community Guidelines. You can disconnect
                an account at any time from instagod or from the platform&apos;s settings.
              </p>
            </>
          ),
        },
        {
          titulo: "4. Your content",
          contenido: (
            <p>
              You keep all rights to the content you create or upload. You grant instagod only the
              permissions needed to store, process and publish that content as you instruct. You
              must have the rights to everything you publish, including images, music and text, and
              it must not infringe the rights of others or break the law.
            </p>
          ),
        },
        {
          titulo: "5. Acceptable use",
          contenido: (
            <p>
              You may not use instagod to publish spam, misleading or illegal content, to
              impersonate others, or to interfere with the service or the platforms it connects to.
            </p>
          ),
        },
        {
          titulo: "6. Disclaimer and liability",
          contenido: (
            <p>
              instagod is provided &quot;as is&quot;, without warranties of any kind. We are not
              liable for indirect or consequential damages, or for actions taken by third-party
              platforms, such as content removal or account restrictions.
            </p>
          ),
        },
        {
          titulo: "7. Changes",
          contenido: (
            <p>
              We may update these terms. The date at the top of this page shows the latest
              version. Continued use after a change means you accept the updated terms.
            </p>
          ),
        },
        {
          titulo: "8. Contact",
          contenido: (
            <p>
              Questions about these terms:{" "}
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
