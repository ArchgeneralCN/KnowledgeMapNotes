import svgLoader from 'vite-svg-loader'

export default function createSvgIcon(isBuild) {
    return svgLoader({
        defaultImport: 'component',
        // Keep the SVG markup identical in dev and production. SVGO's
        // production-only transformations can change inherited fills and
        // viewBox handling, making icon components render blank after build.
        svgo: false
    })
}
