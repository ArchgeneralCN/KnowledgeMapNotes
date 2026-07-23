import svgLoader from 'vite-svg-loader'

export default function createSvgIcon(isBuild) {
    return svgLoader({
        defaultImport: 'component',
        svgo: isBuild
    })
}
