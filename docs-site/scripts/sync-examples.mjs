import { createHash } from 'node:crypto'
import { access, cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const docsSiteRoot = path.resolve(scriptDirectory, '..')
const repositoryRoot = path.resolve(docsSiteRoot, '..')
const sourceRoot = path.join(repositoryRoot, 'backend', 'results')
const coversRoot = path.join(docsSiteRoot, 'covers')
const targetRoot = path.join(docsSiteRoot, 'docs', 'public', 'examples')
const generatedModule = path.join(
  docsSiteRoot,
  'docs',
  '.vitepress',
  'theme',
  'generated',
  'examples.js'
)
const manifestFile = path.join(targetRoot, 'manifest.json')

const localLibraryFiles = [
  {
    source: path.join(repositoryRoot, 'backend', 'lib', 'vis-9.1.2', 'vis-network.min.js'),
    target: 'vis-network.min.js'
  },
  {
    source: path.join(repositoryRoot, 'backend', 'lib', 'vis-9.1.2', 'vis-network.css'),
    target: 'vis-network.min.css'
  }
]

const pathExists = async filePath => {
  try {
    await access(filePath)
    return true
  } catch {
    return false
  }
}

const listFiles = async directory => {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...await listFiles(entryPath))
    } else if (entry.isFile()) {
      files.push(entryPath)
    }
  }

  return files
}

const replaceRemoteGraphAssets = html => html
  .replace(
    /<link[^>]+href="https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/vis-network\/[^\"]+\/vis-network\.min\.css"[^>]*\/?>/g,
    '<link rel="stylesheet" href="../_lib/vis-network.min.css">'
  )
  .replace(
    /<script[^>]+src="https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/vis-network\/[^\"]+\/vis-network\.min\.js"[^>]*><\/script>/g,
    '<script src="../_lib/vis-network.min.js"></script>'
  )
  .replace(/[ \t]+$/gm, '')

const encodePublicPath = (...segments) => `/examples/${segments.map(encodeURIComponent).join('/')}`
const coverExtensions = new Set(['.png', '.jpg', '.jpeg', '.webp', '.avif'])

const isCoverImage = file => {
  if (!file.isFile()) return false
  const extension = path.extname(file.name).toLowerCase()
  return coverExtensions.has(extension)
}

const findCoverSource = async (graphName, resultFiles) => {
  const externalFiles = await readdir(coversRoot, { withFileTypes: true }).catch(() => [])
  const exactPrefix = `${graphName.toLowerCase()}_`
  const externalMatch = externalFiles
    .filter(isCoverImage)
    .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
    .find(file => {
      const stem = path.basename(file.name, path.extname(file.name)).toLowerCase()
      return stem === graphName.toLowerCase() || stem.startsWith(exactPrefix)
    })

  if (externalMatch) {
    return {
      source: path.join(coversRoot, externalMatch.name),
      filename: `cover${path.extname(externalMatch.name).toLowerCase()}`
    }
  }

  const localMatch = resultFiles
    .filter(isCoverImage)
    .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
    .find(file => {
      const stem = path.basename(file.name, path.extname(file.name)).toLowerCase()
      return ['cover', 'thumbnail', '封面'].includes(stem)
    })

  return localMatch
    ? { source: path.join(sourceRoot, graphName, localMatch.name), filename: localMatch.name }
    : null
}

const getDirectorySize = async directory => {
  const files = await listFiles(directory)
  const sizes = await Promise.all(files.map(async filePath => (await stat(filePath)).size))
  return sizes.reduce((total, size) => total + size, 0)
}

const findGraphDirectories = async () => {
  if (!await pathExists(sourceRoot)) return []

  const entries = await readdir(sourceRoot, { withFileTypes: true })
  const directories = []

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue

    const directory = path.join(sourceRoot, entry.name)
    const files = await readdir(directory, { withFileTypes: true })
    const htmlFiles = files
      .filter(file => file.isFile() && file.name.endsWith('.html'))
      .map(file => file.name)

    if (!htmlFiles.length) continue

    const preferredMainFile = `${entry.name}.html`
    const mainFile = htmlFiles.includes(preferredMainFile)
      ? preferredMainFile
      : htmlFiles.find(file => !file.includes('_community_')) || htmlFiles[0]

    directories.push({
      name: entry.name,
      directory,
      mainFile,
      cover: await findCoverSource(entry.name, files),
      pageCount: htmlFiles.length,
      sizeBytes: await getDirectorySize(directory)
    })
  }

  return directories.sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
}

const syncExistingCovers = async () => {
  if (!await pathExists(manifestFile)) return 0

  const manifest = JSON.parse(await readFile(manifestFile, 'utf8'))
  let synced = 0

  for (const example of manifest.examples || []) {
    const cover = await findCoverSource(example.name, [])
    if (!cover) continue

    const publicDirectory = `graph-${example.id}`
    const targetDirectory = path.join(targetRoot, publicDirectory)
    if (!await pathExists(targetDirectory)) continue

    await cp(cover.source, path.join(targetDirectory, cover.filename))
    example.coverUrl = encodePublicPath(publicDirectory, cover.filename)
    synced += 1
  }

  if (synced) {
    const moduleSource = `// Generated by scripts/sync-examples.mjs. Do not edit manually.\nexport const graphExamples = ${JSON.stringify(manifest.examples, null, 2)}\n`
    await writeFile(generatedModule, moduleSource, 'utf8')
    await writeFile(manifestFile, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  }

  return synced
}

const graphDirectories = await findGraphDirectories()

if (!graphDirectories.length) {
  const syncedCovers = await syncExistingCovers()
  console.log(`No generated graphs found; kept existing examples and synced ${syncedCovers} covers.`)
  process.exit(0)
}

await rm(targetRoot, { recursive: true, force: true })
await mkdir(path.join(targetRoot, '_lib'), { recursive: true })
await mkdir(path.dirname(generatedModule), { recursive: true })

for (const libraryFile of localLibraryFiles) {
  await cp(libraryFile.source, path.join(targetRoot, '_lib', libraryFile.target))
}

const accents = ['green', 'coral', 'blue', 'gold']
const examples = []

for (const [index, graph] of graphDirectories.entries()) {
  const id = createHash('sha1').update(graph.name).digest('hex').slice(0, 12)
  const publicDirectory = `graph-${id}`
  const targetDirectory = path.join(targetRoot, publicDirectory)
  await cp(graph.directory, targetDirectory, { recursive: true })

  const copiedFiles = await listFiles(targetDirectory)
  const htmlFiles = copiedFiles.filter(filePath => filePath.endsWith('.html'))

  for (const htmlFile of htmlFiles) {
    const html = await readFile(htmlFile, 'utf8')
    await writeFile(htmlFile, replaceRemoteGraphAssets(html), 'utf8')
  }

  const entryFile = 'index.html'
  if (graph.mainFile !== entryFile) {
    await cp(path.join(targetDirectory, graph.mainFile), path.join(targetDirectory, entryFile))
    await rm(path.join(targetDirectory, graph.mainFile))
  }

  if (graph.cover) {
    await cp(graph.cover.source, path.join(targetDirectory, graph.cover.filename))
  }

  const graphUrl = encodePublicPath(publicDirectory, entryFile)
  examples.push({
    id,
    name: graph.name,
    filename: graph.mainFile,
    graphUrl,
    coverUrl: graph.cover
      ? encodePublicPath(publicDirectory, graph.cover.filename)
      : '/app-preview.png',
    pageCount: graph.pageCount,
    sizeBytes: graph.sizeBytes,
    accent: accents[index % accents.length]
  })
}

const moduleSource = `// Generated by scripts/sync-examples.mjs. Do not edit manually.\nexport const graphExamples = ${JSON.stringify(examples, null, 2)}\n`
await writeFile(generatedModule, moduleSource, 'utf8')
await writeFile(manifestFile, `${JSON.stringify({ examples }, null, 2)}\n`, 'utf8')

console.log(`Synced ${examples.length} graph examples (${examples.reduce((total, item) => total + item.pageCount, 0)} HTML pages).`)
