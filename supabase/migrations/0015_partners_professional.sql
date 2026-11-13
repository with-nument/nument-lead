-- 0015_partners_professional.sql : two new domains (founder, 13 Nov 2026)
--
-- partners      marketing, advertising, branding and design agencies as white-label partners: they sell, Nument
--               builds. A partner is a steady source of repeat work and retainers.
-- professional  law firms and accounting practices (US, UK, Australia first): high-ticket, enquiry-driven
--               businesses that need client intake and follow-up.
-- The domain list stays in step with models.Domain.

alter table public.segments drop constraint if exists segments_domain_check;
alter table public.segments add constraint segments_domain_check check (domain in
  ('clinics','realestate','education','d2c','hospitality','auto','finance','wellness','firms','partners',
   'professional'));
