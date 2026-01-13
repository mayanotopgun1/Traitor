pub struct View<A>(A);
pub trait Data {
    type Elem;
}
impl<'a, A> Data for View<&'a A> {
    type Elem = A;
}

pub fn repro<'a, T>()
where
    <View<&'a T> as Data>::Elem: Sized,
{
}