# Test fixtures

## Anonymized real excerpts (observed in November 2026)

- `login_page.html`: sign-in form of `https://www.mel-ileo.fr/connexion.aspx`
  (`email` and `password` fields, `valider` button).
- `dashboard_page.html`: page shown after signing in
  (`espaceperso/tableau-de-bord.aspx`), with the contract selector (`switchAbt`).
- `export_real_anonymized.csv`: export of `mes-consommations.aspx?ex=1`, exact format
  (header, `;` separator, ISO dates, litres, empty "écoulement permanent") but
  **made-up values and indexes**.

Never put a real address, contract or meter number, or real consumption values here.

## Synthetic files

- `dashboard_page_two_contracts.html`: the dashboard as it is *assumed* to look for an
  account with two contracts. This case was never observed on the real portal.
- `export_synthetic.csv` and `export_synthetic_consumption_only.csv`: made-up variants
  (units in m³ in the header, preamble, duplicates, empty lines) used to test the
  tolerance of the parser and the statistics computation.
