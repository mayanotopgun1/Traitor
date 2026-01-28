use rand::{Rng, seq::SliceRandom};
use syn::parse_quote;
use syn::{GenericParam, Ident, ImplItem, ItemTrait, TraitItem, TraitItemFn, Type};

use crate::ttdn::TtdnInfo;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TraitPattern {
	Basic,
	AssocType,
	Gat,
}

pub fn choose_pattern() -> TraitPattern {
	let mut rng = rand::thread_rng();
	match rng.gen_range(0..3) {
		0 => TraitPattern::Basic,
		1 => TraitPattern::AssocType,
		_ => TraitPattern::Gat,
	}
}

pub fn build_trait(ident: &Ident, pattern: TraitPattern) -> ItemTrait {
	match pattern {
		TraitPattern::Basic => parse_quote!(trait #ident {}),
		TraitPattern::AssocType => parse_quote!(trait #ident { type Assoc; }),
		TraitPattern::Gat => parse_quote!(trait #ident { type Item<'a>; }),
	}
}

pub fn infer_pattern(tr: &ItemTrait) -> TraitPattern {
	let mut has_assoc = false;
	let mut has_gat = false;
	for it in &tr.items {
		if let TraitItem::Type(t) = it {
			if !t.generics.params.is_empty() {
				has_gat = true;
			} else {
				has_assoc = true;
			}
		}
	}
	if has_gat {
		TraitPattern::Gat
	} else if has_assoc {
		TraitPattern::AssocType
	} else {
		TraitPattern::Basic
	}
}

pub fn make_impl_items_for_trait(tr: &ItemTrait, ttdn: &TtdnInfo) -> Vec<ImplItem> {
	let mut out: Vec<ImplItem> = Vec::new();

	for it in &tr.items {
		match it {
			TraitItem::Type(assoc) if assoc.default.is_none() => {
				let assoc_ident = &assoc.ident;
			let base_ty: Type = {
				let mut candidates: Vec<syn::Ident> = ttdn.types.clone();
				candidates.push(syn::Ident::new("i32", proc_macro2::Span::call_site()));
				let chosen = candidates
					.choose(&mut rand::thread_rng())
					.cloned()
					.unwrap();
				parse_quote!(#chosen)
			};
				let lt = assoc
					.generics
					.params
					.iter()
					.find_map(|p| match p {
						GenericParam::Lifetime(lt) => Some(lt.lifetime.clone()),
						_ => None,
					});

				let rhs_ty: Type = if let Some(lifetime) = lt {
					parse_quote!(&#lifetime #base_ty)
				} else {
					base_ty
				};

				if assoc.generics.params.is_empty() {
					out.push(parse_quote!(type #assoc_ident = #rhs_ty;));
				} else {
					let gen = &assoc.generics;
					out.push(parse_quote!(type #assoc_ident #gen = #rhs_ty;));
				}
			}
			TraitItem::Fn(TraitItemFn { sig, default, .. }) if default.is_none() => {
				let sig = sig.clone();
				out.push(parse_quote!(#sig { unimplemented!() }));
			}
			_ => {}
		}
	}

	out
}
