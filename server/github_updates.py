"""Import the two public stable manifests, without downloading binaries to Pi."""
from agent.github_releases import PLATFORMS,manifest

SCHEMA='CREATE TABLE IF NOT EXISTS github_packages (package INTEGER PRIMARY KEY,url TEXT);'


def sync(db):
    # Read/validate everything before starting a write transaction or changing the catalog.
    releases=[manifest(platform) for platform in PLATFORMS]
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for release in releases:
            row=c.execute('SELECT * FROM update_packages WHERE sha256=?',(release['sha256'],)).fetchone()
            if row:
                if row['platform']!=release['platform'] or row['version']!=release['version'] or row['size']!=release['size']:
                    raise ValueError('Conflicting package metadata')
                # Existing local packages remain local, for compatibility with manual staging.
                if not c.execute('SELECT 1 FROM github_packages WHERE package=?',(row['id'],)).fetchone():continue
                package=row['id']
            else:
                package=c.execute('INSERT INTO update_packages(platform,version,sha256,size,path) VALUES (?,?,?,?,?)',
                    (release['platform'],release['version'],release['sha256'],release['size'],'github')).lastrowid
            c.execute('INSERT INTO github_packages VALUES (?,?) ON CONFLICT(package) DO UPDATE SET url=excluded.url',(package,release['download_url']))
    return len(releases)
