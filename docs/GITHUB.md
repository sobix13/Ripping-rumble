# Publish the reviewed source

The source tree is prepared for a new reviewed commit. No repository URL is assumed. The GitHub connector did not expose a confirmed destination for this Rumble project. No remote push or deployment is claimed.

The downloadable bundle includes source plus a local Git bundle on branch release/1.2.0. Clone that bundle into a new local directory, inspect it, then set the actual destination:

```bash
git clone ripcars-rumble-1.2.0.bundle rumble-release
cd rumble-release
git remote remove origin
git remote add origin YOUR_CONFIRMED_REPOSITORY_URL
git push -u origin release/1.2.0
```

For an existing repository, import the release on a new review branch and preserve its existing history. Do not force-push the independent release commit over an existing branch. Review the source diff and let CI complete before merging.

GitHub Actions has read-only contents permissions and never receives deployment credentials. Production tokens, populated .env files, databases, backups, caches and logs from the actual server must remain outside Git. Test evidence under docs/verification is generated from synthetic members.

The static release scan is a local check, not an exhaustive historical secret audit. Enable the repository's available secret scanning and branch protection after choosing the destination. CI is configured for Python3.10 and3.12, while local release execution used3.12.
