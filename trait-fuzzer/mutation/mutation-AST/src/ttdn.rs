use quote::ToTokens;
use rand::seq::SliceRandom;
use syn::visit::{self, Visit};
use syn::{Ident, ItemEnum, ItemImpl, ItemStruct, ItemTrait, TraitItem, Type, TypeParamBound};

#[derive(Debug, Default, Clone)]
pub struct TtdnInfo {
    pub traits: Vec<Ident>,
    pub types: Vec<Ident>,

    // (Type implements Trait)
    pub impl_edges: Vec<(Ident, Ident)>,

    // (Trait has supertrait)
    pub supertrait_edges: Vec<(Ident, Ident)>,

    // (Trait declares associated type)
    pub trait_assoc_types: Vec<(Ident, Ident)>,

    // impl Type: assoc bindings like `type Assoc = Ty;` inside `impl Trait for Type`.
    pub impl_assoc_bindings: Vec<ImplAssocBinding>,
}

#[derive(Debug, Clone)]
pub struct ImplAssocBinding {
    pub self_ty: Ident,
    pub trait_ident: Ident,
    pub assoc_ident: Ident,
    pub rhs_ty: syn::Type,
}

impl TtdnInfo {
    pub fn from_file(ast: &syn::File) -> Self {
        struct Collector {
            info: TtdnInfo,
        }

        impl<'ast> Visit<'ast> for Collector {
            fn visit_item_trait(&mut self, i: &'ast ItemTrait) {
                self.info.traits.push(i.ident.clone());

                for item in &i.items {
                    if let TraitItem::Type(assoc) = item {
                        self.info
                            .trait_assoc_types
                            .push((i.ident.clone(), assoc.ident.clone()));
                    }
                }

                for bound in &i.supertraits {
                    if let TypeParamBound::Trait(tb) = bound {
                        if let Some(super_ident) = tb.path.get_ident() {
                            self.info
                                .supertrait_edges
                                .push((i.ident.clone(), super_ident.clone()));
                        }
                    }
                }

                visit::visit_item_trait(self, i);
            }

            fn visit_item_struct(&mut self, i: &'ast ItemStruct) {
                self.info.types.push(i.ident.clone());
                visit::visit_item_struct(self, i);
            }

            fn visit_item_enum(&mut self, i: &'ast ItemEnum) {
                self.info.types.push(i.ident.clone());
                visit::visit_item_enum(self, i);
            }

            fn visit_item_impl(&mut self, i: &'ast ItemImpl) {
                if let Some((_, trait_path, _)) = &i.trait_ {
                    if let Some(trait_ident) = trait_path.get_ident() {
                        if let Type::Path(self_ty) = &*i.self_ty {
                            if let Some(type_ident) = self_ty.path.get_ident() {
                                self.info
                                    .impl_edges
                                    .push((type_ident.clone(), trait_ident.clone()));

                                for impl_item in &i.items {
                                    if let syn::ImplItem::Type(assoc) = impl_item {
                                        self.info.impl_assoc_bindings.push(ImplAssocBinding {
                                            self_ty: type_ident.clone(),
                                            trait_ident: trait_ident.clone(),
                                            assoc_ident: assoc.ident.clone(),
                                            rhs_ty: assoc.ty.clone(),
                                        });
                                    }
                                }
                            }
                        }
                    }
                }

                visit::visit_item_impl(self, i);
            }
        }

        let mut c = Collector {
            info: TtdnInfo::default(),
        };
        c.visit_file(ast);

        // Keep lists stable and reasonably unique.
        c.info
            .traits
            .sort_by(|a, b| a.to_string().cmp(&b.to_string()));
        c.info.traits.dedup_by(|a, b| a == b);
        c.info
            .types
            .sort_by(|a, b| a.to_string().cmp(&b.to_string()));
        c.info.types.dedup_by(|a, b| a == b);
        c.info.impl_edges.sort_by(|(ta, tr_a), (tb, tr_b)| {
            (ta.to_string(), tr_a.to_string()).cmp(&(tb.to_string(), tr_b.to_string()))
        });
        c.info.impl_edges.dedup_by(|a, b| a.0 == b.0 && a.1 == b.1);
        c.info.supertrait_edges.sort_by(|(t1, s1), (t2, s2)| {
            (t1.to_string(), s1.to_string()).cmp(&(t2.to_string(), s2.to_string()))
        });
        c.info.supertrait_edges.dedup_by(|a, b| a.0 == b.0 && a.1 == b.1);

        c.info.trait_assoc_types.sort_by(|(t1, a1), (t2, a2)| {
            (t1.to_string(), a1.to_string()).cmp(&(t2.to_string(), a2.to_string()))
        });
        c.info
            .trait_assoc_types
            .dedup_by(|a, b| a.0 == b.0 && a.1 == b.1);

        c.info.impl_assoc_bindings.sort_by(|a, b| {
            (
                a.self_ty.to_string(),
                a.trait_ident.to_string(),
                a.assoc_ident.to_string(),
                a.rhs_ty.to_token_stream().to_string(),
            )
                .cmp(&(
                    b.self_ty.to_string(),
                    b.trait_ident.to_string(),
                    b.assoc_ident.to_string(),
                    b.rhs_ty.to_token_stream().to_string(),
                ))
        });
        c.info.impl_assoc_bindings.dedup_by(|a, b| {
            a.self_ty == b.self_ty
                && a.trait_ident == b.trait_ident
                && a.assoc_ident == b.assoc_ident
                && a.rhs_ty.to_token_stream().to_string() == b.rhs_ty.to_token_stream().to_string()
        });

        c.info
    }

    pub fn any_constraint_pair(&self) -> Option<(Ident, Ident)> {
        let mut rng = rand::thread_rng();
        self.impl_edges.choose(&mut rng).cloned()
    }

    /// Complexity summary used by the Python driver for seed selection/stagnation.
    ///
    /// We build a directed graph over names:
    /// - Type -> Trait edges from impls
    /// - Trait -> Supertrait edges from inheritance
    ///
    /// Returns (max_depth, cycle_count).
    pub fn complexity(&self) -> (u32, u32) {
        use std::collections::{HashMap, HashSet};

        let mut nodes: HashSet<String> = HashSet::new();
        for t in &self.traits {
            nodes.insert(t.to_string());
        }
        for ty in &self.types {
            nodes.insert(ty.to_string());
        }

        let mut adj: HashMap<String, Vec<String>> = HashMap::new();
        for (ty, tr) in &self.impl_edges {
            adj.entry(ty.to_string()).or_default().push(tr.to_string());
            nodes.insert(ty.to_string());
            nodes.insert(tr.to_string());
        }
        for (tr, sup) in &self.supertrait_edges {
            adj.entry(tr.to_string()).or_default().push(sup.to_string());
            nodes.insert(tr.to_string());
            nodes.insert(sup.to_string());
        }

        let mut visited: HashSet<String> = HashSet::new();
        let mut stack: HashSet<String> = HashSet::new();
        let mut max_depth: u32 = 0;
        let mut cycles: u32 = 0;

        fn dfs(
            node: &str,
            depth: u32,
            adj: &HashMap<String, Vec<String>>,
            visited: &mut HashSet<String>,
            stack: &mut HashSet<String>,
            max_depth: &mut u32,
            cycles: &mut u32,
        ) {
            visited.insert(node.to_string());
            stack.insert(node.to_string());
            *max_depth = (*max_depth).max(depth);

            if let Some(children) = adj.get(node) {
                for child in children {
                    if !visited.contains(child) {
                        dfs(child, depth + 1, adj, visited, stack, max_depth, cycles);
                    } else if stack.contains(child) {
                        *cycles += 1;
                    }
                }
            }

            stack.remove(node);
        }

        for n in nodes.iter() {
            if !visited.contains(n) {
                dfs(n, 1, &adj, &mut visited, &mut stack, &mut max_depth, &mut cycles);
            }
        }

        (max_depth, cycles)
    }
}
