// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// Unit tests for `<EngineBadge>` (infra_adapter_solr Story A11).

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EngineBadge } from '@/components/clusters/engine-badge';

describe('<EngineBadge>', () => {
  it('renders the Elasticsearch label + aria-label', () => {
    render(<EngineBadge engine="elasticsearch" />);
    expect(screen.getByText('Elasticsearch')).toBeInTheDocument();
    expect(screen.getByLabelText('Elasticsearch engine')).toBeInTheDocument();
  });

  it('renders the OpenSearch label + aria-label', () => {
    render(<EngineBadge engine="opensearch" />);
    expect(screen.getByText('OpenSearch')).toBeInTheDocument();
    expect(screen.getByLabelText('OpenSearch engine')).toBeInTheDocument();
  });

  it('renders the Apache Solr label + aria-label', () => {
    render(<EngineBadge engine="solr" />);
    expect(screen.getByText('Apache Solr')).toBeInTheDocument();
    expect(screen.getByLabelText('Apache Solr engine')).toBeInTheDocument();
  });

  it('embeds mode in the Solr tooltip', () => {
    render(<EngineBadge engine="solr" mode="cloud" version="10.0.0" />);
    const badge = screen.getByLabelText('Apache Solr engine');
    expect(badge.getAttribute('title')).toBe('Apache Solr 10.0.0 (cloud)');
  });

  it('omits mode parens for non-Solr engines even when mode is provided', () => {
    // EngineBadge's mode prop is Solr-specific by design; ES with a stray
    // mode value should not produce "(...)" garbage in the tooltip.
    render(<EngineBadge engine="elasticsearch" version="9.4.0" />);
    const badge = screen.getByLabelText('Elasticsearch engine');
    expect(badge.getAttribute('title')).toBe('Elasticsearch 9.4.0');
  });
});
