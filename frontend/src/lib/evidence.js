const blockId = (value) => String(
  value && typeof value === 'object'
    ? value.source_block || value.bid || ''
    : value || '',
);

const uniqueTerms = (values) => [...new Set(
  (values || []).map((value) => String(value || '').trim()).filter(Boolean),
)];

export function inferHighlightTerms(message, graphData, references) {
  const ids = new Set(references.map(blockId).filter(Boolean));
  const includesBlock = (values) => (values || []).some((value) => ids.has(blockId(value)));
  const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
  const links = Array.isArray(graphData?.links) ? graphData.links : [];
  const relatedNodes = nodes.filter((node) => includesBlock(node.source_blocks));
  const relatedLinks = links.filter((link) => includesBlock(link.evidence_blocks)
    || ids.has(blockId(link.source_block)));

  const selectedNode = nodes.find((node) => String(node.id) === String(message.id))
    || relatedNodes[0];
  const requestedRelationTerms = uniqueTerms(message.relationTerms || []);
  const requestedEntityTerms = uniqueTerms(message.entityTerms || []);
  const selectedLink = links.find((link) => String(link.id) === String(message.id))
    || relatedLinks.find((link) => requestedRelationTerms.includes(String(link.relation || ''))
      && [link.source, link.target].some((value) => requestedEntityTerms.includes(String(value || ''))))
    || relatedLinks.find((link) => requestedRelationTerms.includes(String(link.relation || '')))
    || relatedLinks[0];

  return {
    entityTerms: uniqueTerms([
      ...relatedNodes.flatMap((node) => [node.name, node.id]),
      ...relatedLinks.flatMap((link) => [link.source, link.target]),
    ]),
    relationTerms: uniqueTerms(relatedLinks.map((link) => link.relation)),
    evidenceTerms: uniqueTerms(relatedLinks.flatMap((link) => [link.context, link.evidence])),
    selectedEntityTerms: message.kind === 'node'
      ? uniqueTerms([selectedNode?.name, selectedNode?.id, ...(message.entityTerms || [])])
      : uniqueTerms([selectedLink?.source, selectedLink?.target]),
    selectedRelationTerms: message.kind === 'edge'
      ? uniqueTerms([selectedLink?.relation, ...(message.relationTerms || [])])
      : [],
    selectedEvidenceTerms: message.kind === 'edge'
      ? uniqueTerms([selectedLink?.context, selectedLink?.evidence])
      : [],
  };
}

export function inferIndexedHighlightTerms(message, blocks, references) {
  const ids = new Set(references.map(blockId).filter(Boolean));
  const relatedBlocks = (Array.isArray(blocks) ? blocks : [])
    .filter((block) => ids.has(String(block?.bid || '')));
  const indexedTerms = relatedBlocks.map((block) => block.highlight_terms || {});
  const selectedEntityTerms = uniqueTerms(message.entityTerms || []);
  const selectedRelationTerms = uniqueTerms(message.relationTerms || []);
  const selectedEvidenceTerms = uniqueTerms(references
    .map((reference) => typeof reference === 'object' ? reference.evidence : ''));

  return {
    entityTerms: uniqueTerms(indexedTerms.flatMap((terms) => terms.entityTerms || [])),
    relationTerms: uniqueTerms(indexedTerms.flatMap((terms) => terms.relationTerms || [])),
    evidenceTerms: uniqueTerms(indexedTerms.flatMap((terms) => terms.evidenceTerms || [])),
    selectedEntityTerms,
    selectedRelationTerms: message.kind === 'edge' ? selectedRelationTerms : [],
    selectedEvidenceTerms: message.kind === 'edge' ? selectedEvidenceTerms : [],
  };
}

export { blockId };
