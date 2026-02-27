use std::marker::PhantomData;
trait Callable<'a>: Send + Sync {
    fn callable(data: &'a [u8]);
}
trait Getter<'a>: Send + Sync {
    type ItemSize: Send + Sync;
    fn get(data: &'a [u8]);
}
struct List<'a, A: Getter<'a>> {
    data: &'a [u8],
    item_size: A::ItemSize,
    phantom: PhantomData<A>,
}
impl<'a, A: Getter<'a> + Getter> List<'a, A> {
    fn new(data: &'a [u8]) -> Self {
        List {
            data,
            item_size: Default::default(),
            phantom: PhantomData,
        }
    }
}
struct GetterImpl<T: Callable + 'static> {
    _phantom: PhantomData<T>,
}
impl<'a, T: Callable + 'static> Getter<'a> for GetterImpl<T> {
    type ItemSize = ();
    fn get(data: &'a [u8]) {
        T::callable(data);
    }
}
struct ConstructableImpl;
impl Callable for ConstructableImpl {
    fn callable(_: &[u8]) {}
}
struct StructWithLifetime<'a> {
    marker: &'a PhantomData<u8>,
}
async fn async_method() {}
fn assert_send(_: impl Send + Sync) {}
async fn my_send_async_method(
    _struct_with_lifetime: &mut StructWithLifetime<'_>,
    data: &[u8],
) {
    let _named = List::new::<GetterImpl<ConstructableImpl>>(data);
    async_method().await;
    assert_send(_named);
}
fn dummy(struct_with_lifetime: &mut StructWithLifetime<'_>, data: &[u8]) {
    assert_send(my_send_async_method(struct_with_lifetime, data));
}
fn main() {}
