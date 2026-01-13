pub trait Typed {}
pub struct SpeciesCases<E>(E);
pub trait SpeciesPackedElim {
    type Ogre;
    type Cyclops;

}
impl<'b, E: SpeciesPackedElim> Typed for &'b SpeciesCases<E>
where
    &'b E::Ogre: Typed,
    &'b E::Cyclops: Typed,
{}
fn foo<T: Typed>() {}
fn main() {
    foo::<&_>();
}

